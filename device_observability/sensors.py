from __future__ import annotations

import hashlib
import platform
import queue
import re
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from . import __version__
from .processes import ProcessCollector


@dataclass(frozen=True)
class Source:
    id: str
    collector: str
    metric: str
    unit: str
    kind: str
    scope: str
    path: str = ""
    label: str = ""
    parent_domain: str | None = None
    max_range: int | None = None
    output_unit: str | None = None
    scale: float = 1

    def document(self) -> dict:
        return asdict(self)


def source(collector: str, identity: str, metric: str, unit: str, **kwargs) -> Source:
    key = f"{collector}:{identity}:{metric}"
    return Source(hashlib.sha256(key.encode()).hexdigest()[:24], collector, metric, unit, **kwargs)


def read_int(path: Path) -> int:
    return int(path.read_text().strip())


class Collector:
    def __init__(self, sys_root: Path = Path("/sys"), proc_root: Path = Path("/proc")):
        self.sys = sys_root
        self.proc = proc_root
        self.sources: list[Source] = []

    def discover(self) -> list[Source]:
        raise NotImplementedError

    def read(self) -> tuple[list[dict], list[Source]]:
        readings = []
        for item in self.sources:
            try:
                readings.append({"source_id": item.id, "value": read_int(Path(item.path)), "quality": "ok"})
            except (OSError, ValueError) as exc:
                readings.append({"source_id": item.id, "value": None, "quality": "error", "error": type(exc).__name__})
        return readings, self.sources

    def identity(self, path: Path) -> str:
        # hwmon/card indices change after reboot or hotplug; physical device paths do not.
        relative = str(path.resolve().relative_to(self.sys.resolve()))
        return re.sub(r"/hwmon/hwmon\d+", "", relative)


class PowercapCollector(Collector):
    def discover(self) -> list[Source]:
        result = []
        seen = set()
        for directory in sorted((self.sys / "class/powercap").glob("*")):
            path = directory / "energy_uj"
            if not path.exists() or str(path.resolve()) in seen:
                continue
            seen.add(str(path.resolve()))
            domain = directory.resolve()
            names = []
            for ancestor in [*reversed(domain.parents), domain]:
                if (ancestor / "energy_uj").exists() and (ancestor / "name").exists():
                    names.append((ancestor / "name").read_text().strip())
            label = "/".join(names) or directory.name
            try:
                max_range = read_int(directory / "max_energy_range_uj")
            except (OSError, ValueError):
                max_range = None
            result.append(source("powercap", label, "cpu.energy_reported", "uJ", kind="counter",
                                 scope=label, path=str(path), label=label,
                                 parent_domain="/".join(names[:-1]) or None, max_range=max_range,
                                 output_unit="J", scale=1e-6))
        self.sources = result
        return result


class GPUCollector(Collector):
    def discover(self) -> list[Source]:
        result = []
        for card in sorted((self.sys / "class/drm").glob("card[0-9]*")):
            if not re.fullmatch(r"card\d+", card.name) or not (card / "device").exists():
                continue
            device = card / "device"
            identity = self.identity(device)
            for filename, metric, unit in (
                ("gpu_busy_percent", "gpu.utilization", "percent"),
                ("mem_busy_percent", "gpu.memory_utilization", "percent"),
                ("mem_info_vram_used", "gpu.vram_used", "bytes"),
                ("mem_info_vram_total", "gpu.vram_total", "bytes"),
            ):
                path = device / filename
                if path.exists():
                    result.append(source("gpu", identity, metric, unit, kind="gauge", scope=identity, path=str(path)))
            for hwmon in sorted((device / "hwmon").glob("hwmon*")):
                for path in sorted(hwmon.glob("power*_average")):
                    # Power caps are configuration, never measurements.
                    result.append(source("gpu", identity + ":" + path.name, "gpu.power_reported", "uW",
                                         kind="gauge", scope=identity, path=str(path), label="reported SoC power",
                                         output_unit="W", scale=1e-6))
        self.sources = result
        return result


class ThermalCollector(Collector):
    def discover(self) -> list[Source]:
        result = []
        for directory in sorted((self.sys / "class/hwmon").glob("hwmon*")):
            try:
                name = (directory / "name").read_text().strip()
                identity = self.identity(directory)
            except OSError:
                continue
            if name.startswith(("hidpp", "hid_", "ucsi")) or "/usb" in identity:
                continue  # External peripherals are outside this collector's scope.
            for pattern, metric, unit, output, scale in (
                ("temp*_input", "temperature", "mC", "C", 0.001),
                ("fan*_input", "fan.speed", "rpm", "rpm", 1),
            ):
                for path in sorted(directory.glob(pattern)):
                    label_path = path.with_name(path.name.replace("_input", "_label"))
                    try:
                        label = label_path.read_text().strip()
                    except OSError:
                        label = path.stem
                    result.append(source("thermal", identity + ":" + path.name, metric, unit,
                                         kind="gauge", scope=identity, path=str(path), label=f"{name}: {label}",
                                         output_unit=output, scale=scale))
        self.sources = result
        return result


class SystemCollector(Collector):
    def discover(self) -> list[Source]:
        return self.sources

    def read(self) -> tuple[list[dict], list[Source]]:
        readings: list[dict] = []
        sources: list[Source] = []

        def add(identity: str, metric: str, unit: str, value: int | None, kind="gauge", error=None):
            item = source("system", identity, metric, unit, kind=kind, scope=identity)
            sources.append(item)
            entry = {"source_id": item.id, "value": value, "quality": "error" if error else "ok"}
            if error:
                entry["error"] = error
            readings.append(entry)

        try:
            cpu = [int(x) for x in (self.proc / "stat").read_text().splitlines()[0].split()[1:9]]
            add("cpu", "cpu.total", "ticks", sum(cpu), "counter")
            add("cpu", "cpu.idle_including_iowait", "ticks", cpu[3] + cpu[4], "counter")
        except (OSError, ValueError, IndexError) as exc:
            add("cpu", "cpu.total", "ticks", None, "counter", type(exc).__name__)
        try:
            memory = {line.split(':')[0]: int(line.split()[1]) * 1024
                      for line in (self.proc / "meminfo").read_text().splitlines() if line.endswith(" kB")}
            for key, metric in (("MemTotal", "memory.total"), ("MemAvailable", "memory.available"),
                                ("SwapTotal", "swap.total"), ("SwapFree", "swap.free")):
                add("memory", metric, "bytes", memory.get(key), error=None if key in memory else "Unavailable")
        except (OSError, ValueError) as exc:
            add("memory", "memory.available", "bytes", None, error=type(exc).__name__)
        try:
            for line in (self.proc / "net/dev").read_text().splitlines()[2:]:
                name, values = line.split(":")
                name = name.strip()
                if name == "lo":
                    continue
                fields = values.split()
                add("net:" + name, "network.received", "bytes", int(fields[0]), "counter")
                add("net:" + name, "network.sent", "bytes", int(fields[8]), "counter")
        except (OSError, ValueError, IndexError) as exc:
            add("network", "network.received", "bytes", None, "counter", type(exc).__name__)
        try:
            for line in (self.proc / "diskstats").read_text().splitlines():
                fields = line.split()
                name = fields[2]
                if name.startswith(("loop", "ram", "zram")) or not (self.sys / "block" / name).exists():
                    continue
                # Keep individual devices: summing a device mapper and its backing disk double-counts I/O.
                add("disk:" + name, "disk.read", "bytes", int(fields[5]) * 512, "counter")
                add("disk:" + name, "disk.written", "bytes", int(fields[9]) * 512, "counter")
        except (OSError, ValueError, IndexError) as exc:
            add("disk", "disk.read", "bytes", None, "counter", type(exc).__name__)
        self.sources = sources
        return readings, sources


FACTORIES = {"system": SystemCollector, "powercap": PowercapCollector, "gpu": GPUCollector, "thermal": ThermalCollector, "processes": ProcessCollector}


class Worker:
    """One bounded, daemon reader per adapter; stale replies are discarded.

    Python cannot interrupt a kernel read. A stuck adapter occupies just its own
    thread; we never spawn replacements indefinitely and never join it at exit.
    Only the main thread writes the database.
    """

    def __init__(self, collector: Collector, rediscover_seconds: float):
        self.collector = collector
        self.rediscover_seconds = rediscover_seconds
        self.requests: queue.Queue = queue.Queue(maxsize=1)
        self.responses: queue.Queue = queue.Queue(maxsize=1)
        self.busy = False
        self.token = 0
        self.stopped = threading.Event()
        self.rediscover = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True, name=type(collector).__name__)
        self.thread.start()

    def _run(self):
        next_discovery = 0.0
        while True:
            request = self.requests.get()
            if request is None or self.stopped.is_set():
                return
            token, options = request
            started = time.monotonic_ns()
            utc = time.time_ns()
            try:
                if options is not None:
                    self.collector.configure(options)
                if self.rediscover.is_set() or time.monotonic() >= next_discovery:
                    self.rediscover.clear()
                    self.collector.discover()
                    next_discovery = time.monotonic() + self.rediscover_seconds
                readings, sources = self.collector.read()
                result = {"readings": readings, "sources": [s.document() for s in sources], "quality": "ok"}
                if hasattr(self.collector, 'context'):
                    result['context'] = self.collector.context
            except Exception as exc:
                result = {"readings": [], "sources": [], "quality": "error", "error": type(exc).__name__}
            result.update(observed_utc_ns=utc, observed_monotonic_ns=started,
                          duration_ms=(time.monotonic_ns() - started) / 1e6)
            self.responses.put((token, result))
            if self.stopped.is_set():
                return

    def submit(self, token: int, options=None) -> bool:
        if self.busy:
            try:
                self.responses.get_nowait()  # Prior timed-out observation is not part of this cycle.
                self.busy = False
            except queue.Empty:
                return False
        self.token = token
        self.busy = True
        self.requests.put_nowait((token, options))
        return True

    def receive(self, token: int, deadline: float) -> dict:
        if self.token != token:
            return {"quality": "timeout", "error": "PreviousReadStillRunning", "readings": [], "sources": []}
        try:
            reply_token, result = self.responses.get(timeout=max(0, deadline - time.monotonic()))
            self.busy = False
            if reply_token != token:
                raise RuntimeError("unexpected reader token")
            return result
        except queue.Empty:
            return {"quality": "timeout", "error": "ReadDeadlineExceeded", "readings": [], "sources": []}

    def close(self):
        self.stopped.set()
        try:
            self.requests.put_nowait(None)
        except queue.Full:
            pass


class SensorPool:
    def __init__(self, rediscover_seconds: float = 300, factories: dict[str, Callable] | None = None):
        self.factories = factories or FACTORIES
        self.rediscover_seconds = rediscover_seconds
        self.workers: dict[str, Worker] = {}
        self.process_options = {'interval_seconds':30, 'top_n':5}

    def collect(self, names: list[str], token: int, timeout: float) -> dict[str, dict]:
        deadline = time.monotonic() + timeout
        for name in names:
            if name not in self.workers:
                self.workers[name] = Worker(self.factories[name](), self.rediscover_seconds)
            self.workers[name].rediscover_seconds = self.rediscover_seconds
            self.workers[name].submit(token, self.process_options.copy() if name == 'processes' else None)
        return {name: self.workers[name].receive(token, deadline) for name in names}

    def close(self):
        for worker in self.workers.values():
            worker.close()

    def invalidate(self):
        for worker in self.workers.values():
            worker.rediscover.set()


def inventory(proc: Path = Path("/proc")) -> dict:
    result = {"kernel": platform.release(), "architecture": platform.machine()}
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    result.update(collector_version=__version__, collector_source_sha256=digest.hexdigest())
    try:
        for line in (proc / "cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                result["cpu_model"] = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    return result
