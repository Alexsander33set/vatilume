import tempfile
import time
import unittest
from pathlib import Path

from device_observability.analysis import overview, integrate_cost
from device_observability.config import Config
from device_observability.storage import Store

BASE = 1793188800000  # 2026-10-28 12:00 UTC; deterministic, synthetic fixtures.


def synthetic(directory, timestamps=(0, 10, 20), values=(0, 1_000_000_000, 2_000_000_000), bad=False, split=False):
    path = Path(directory) / "telemetry.sqlite3"
    config = Config(Path(directory))
    store = Store(path)
    session = store.start("synthetic-boot", config, {})
    catalog = [
        {"id": "cpu", "collector": "powercap", "metric": "cpu.energy_reported", "unit": "uJ", "kind": "counter", "scope": "package-0", "parent_domain": None, "max_range": 65_000_000_000, "scale": 1e-6, "output_unit": "J"},
        {"id": "core", "collector": "powercap", "metric": "cpu.energy_reported", "unit": "uJ", "kind": "counter", "scope": "core", "parent_domain": "package-0", "max_range": 65_000_000_000, "scale": 1e-6, "output_unit": "J"},
        {"id": "gpu", "collector": "gpu", "metric": "gpu.power_reported", "unit": "uW", "kind": "gauge", "scope": "discrete-gpu", "energy_domain": "discrete_gpu", "scale": 1e-6, "output_unit": "W"},
    ]
    for index, second in enumerate(timestamps):
        if split and index == 1:
            session = store.start("synthetic-boot", config, {})
        utc = (BASE + second * 1000) * 1_000_000
        groups = {name: {"quality": "ok", "observed_utc_ns": utc, "observed_monotonic_ns": second * 1_000_000_000,
                         "duration_ms": 1, "sources": [s for s in catalog if s["collector"] == name], "readings": []} for name in ("powercap", "gpu")}
        groups["powercap"]["readings"] = [{"source_id": "cpu", "value": None if bad else values[index], "quality": "error" if bad else "ok"}, {"source_id": "core", "value": values[index] // 2, "quality": "ok"}]
        groups["gpu"]["readings"] = [{"source_id": "gpu", "value": (10 + 20 * index) * 1_000_000, "quality": "ok"}]
        store.append(session, {"sequence": index + 1, "utc_ns": utc, "monotonic_ns": second * 1_000_000_000,
                              "boottime_ns": second * 1_000_000_000, "collectors": groups, "collection_ms": 1}, config, [])
    store.close()
    return path


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_counter_and_trapezoid_units_and_no_core_double_count(self):
        result = overview(synthetic(self.tmp.name), BASE, BASE + 20_000, [], 24)
        cpu, gpu = result["components"]
        self.assertAlmostEqual(cpu["energy_kwh"], 2000 / 3_600_000)
        self.assertAlmostEqual(gpu["energy_kwh"], 600 / 3_600_000)
        self.assertEqual(cpu["covered_seconds"], 20)
        self.assertIsNone(cpu["cost_brl"])

    def test_tariff_change_splits_actual_energy_without_repricing_history(self):
        tariffs = [{"effective_ms": BASE, "price": "1"}, {"effective_ms": BASE + 10_000, "price": "2"}]
        result = overview(synthetic(self.tmp.name), BASE, BASE + 20_000, tariffs, 24)
        self.assertAlmostEqual(result["components"][0]["cost_brl"], 3000 / 3_600_000)
        self.assertEqual(result["components"][0]["priced_seconds"], 20)

    def test_tariff_missing_for_part_of_window_remains_partial(self):
        result = overview(synthetic(self.tmp.name), BASE, BASE + 20_000, [{"effective_ms": BASE + 5000, "price": "1"}], 24)
        self.assertEqual(result["components"][0]["priced_seconds"], 15)
        self.assertAlmostEqual(result["components"][0]["cost_brl"], 1500 / 3_600_000)

    def test_missing_reading_is_not_zero_energy(self):
        result = overview(synthetic(self.tmp.name, bad=True), BASE, BASE + 20_000, [], 24)
        self.assertIsNone(result["components"][0]["energy_kwh"])
        self.assertEqual(result["quality"]["reading_errors"], 3)

    def test_long_gap_is_not_integrated(self):
        result = overview(synthetic(self.tmp.name, timestamps=(0, 10, 100)), BASE, BASE + 100_000, [], 24)
        self.assertEqual(result["components"][0]["covered_seconds"], 10)
        self.assertAlmostEqual(result["components"][0]["energy_kwh"], 1000 / 3_600_000)

    def test_restart_does_not_join_two_sessions(self):
        result = overview(synthetic(self.tmp.name, split=True), BASE, BASE + 20_000, [], 24)
        self.assertEqual(result["components"][0]["covered_seconds"], 10)

    def test_single_rollover_is_handled(self):
        result = overview(synthetic(self.tmp.name, values=(64_000_000_000, 500_000_000, 1_500_000_000)), BASE, BASE + 20_000, [], 24)
        self.assertAlmostEqual(result["components"][0]["energy_kwh"], 2500 / 3_600_000)

    def test_window_clipping_and_linear_tariff_split(self):
        energy, priced, cost = integrate_cost(BASE, BASE + 10_000, 0, 100, [{"effective_ms": BASE + 5000, "price": "2"}])
        self.assertAlmostEqual(energy, 500 / 3_600_000)
        self.assertAlmostEqual(priced, 375 / 3_600_000)
        self.assertAlmostEqual(cost, 750 / 3_600_000)
