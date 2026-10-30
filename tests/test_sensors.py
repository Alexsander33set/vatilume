import tempfile
import threading
import time
import unittest
from pathlib import Path

from device_observability.sensors import GPUCollector, PowercapCollector, SensorPool, ThermalCollector


class SensorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, path, text):
        location = self.root / path
        location.parent.mkdir(parents=True, exist_ok=True)
        location.write_text(text)
        return location

    def test_powercap_domains_and_raw_counter_are_not_added(self):
        base = "devices/virtual/powercap/intel-rapl/intel-rapl:0"
        for suffix, label, value in (("", "package-0", 1234), ("/intel-rapl:0:0", "core", 400)):
            self.put(base + suffix + "/name", label)
            self.put(base + suffix + "/energy_uj", str(value))
            self.put(base + suffix + "/max_energy_range_uj", "10000000")
        directory = self.root / "class/powercap"
        directory.mkdir(parents=True)
        (directory / "intel-rapl:0").symlink_to(self.root / base)
        (directory / "intel-rapl:0:0").symlink_to(self.root / (base + "/intel-rapl:0:0"))
        collector = PowercapCollector(self.root)
        catalogue = collector.discover()
        self.assertEqual([s.scope for s in catalogue], ["package-0", "package-0/core"])
        self.assertEqual(catalogue[1].parent_domain, "package-0")
        readings, _ = collector.read()
        self.assertEqual([r["value"] for r in readings], [1234, 400])

    def test_hwmon_renumber_preserves_identity_and_missing_is_not_zero(self):
        physical = self.root / "devices/pci0/gpu/hwmon"
        self.put("devices/pci0/gpu/hwmon/hwmon4/name", "amdgpu")
        self.put("devices/pci0/gpu/hwmon/hwmon4/temp1_input", "42000")
        directory = self.root / "class/hwmon"
        directory.mkdir(parents=True)
        (directory / "hwmon4").symlink_to(physical / "hwmon4")
        collector = ThermalCollector(self.root)
        before = collector.discover()[0]
        (directory / "hwmon4").unlink()
        (physical / "hwmon4").rename(physical / "hwmon19")
        (directory / "hwmon19").symlink_to(physical / "hwmon19")
        after = collector.discover()[0]
        self.assertEqual(before.id, after.id)
        Path(after.path).unlink()
        readings, _ = collector.read()
        self.assertIsNone(readings[0]["value"])
        self.assertEqual(readings[0]["quality"], "error")

    def test_gpu_uses_power_reading_and_excludes_cap(self):
        device = self.root / "devices/pci0/gpu"
        self.put("devices/pci0/gpu/gpu_busy_percent", "24")
        self.put("devices/pci0/gpu/hwmon/hwmon4/power1_average", "21000000")
        self.put("devices/pci0/gpu/hwmon/hwmon4/power1_cap", "164000000")
        card = self.root / "class/drm/card1"
        card.mkdir(parents=True)
        (card / "device").symlink_to(device)
        collector = GPUCollector(self.root)
        catalogue = collector.discover()
        self.assertEqual(len(catalogue), 2)
        power = next(s for s in catalogue if s.metric == "gpu.power_reported")
        self.assertEqual(power.scale, 1e-6)
        self.assertFalse(any(s.path.endswith("power1_cap") for s in catalogue))

    def test_peripheral_temperature_is_excluded(self):
        self.put("class/hwmon/hwmon5/name", "hidpp_battery_0")
        self.put("class/hwmon/hwmon5/temp1_input", "25000")
        self.assertEqual(ThermalCollector(self.root).discover(), [])

    def test_stuck_reader_does_not_block_others_or_spawn_unbounded_threads(self):
        release = threading.Event()

        class Slow:
            def discover(self):
                pass

            def read(self):
                release.wait(3)
                return [{"source_id": "old", "value": 10, "quality": "ok"}], []

        class Fast:
            def discover(self):
                pass

            def read(self):
                return [{"source_id": "fast", "value": 20, "quality": "ok"}], []

        pool = SensorPool(factories={"slow": Slow, "fast": Fast})
        try:
            started = time.monotonic()
            result = pool.collect(["slow", "fast"], 1, 0.03)
            self.assertLess(time.monotonic() - started, 0.3)
            self.assertEqual(result["slow"]["quality"], "timeout")
            self.assertEqual(result["fast"]["readings"][0]["value"], 20)
            thread = pool.workers["slow"].thread
            for i in range(2, 10):
                result = pool.collect(["slow", "fast"], i, 0.01)
                self.assertEqual(result["slow"]["readings"], [])
                self.assertIs(pool.workers["slow"].thread, thread)
                self.assertEqual(result["fast"]["quality"], "ok")
        finally:
            release.set()
            pool.close()


if __name__ == "__main__":
    unittest.main()
