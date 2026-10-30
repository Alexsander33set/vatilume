from __future__ import annotations

import logging
import os
import shutil
import signal
import socket
import sqlite3
import threading
import time
from collections import deque
from pathlib import Path

from .config import Config, load_config
from .sensors import SensorPool, inventory
from .schedule import Periodic
from .storage_policy import ensure_capacity, maintain
from .storage import Store, WriterLock, encode

LOG = logging.getLogger(__name__)


def boottime_ns() -> int:
    return time.clock_gettime_ns(time.CLOCK_BOOTTIME)


def process_start_ticks(pid: int) -> int | None:
    try:
        return int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19])
    except (OSError, ValueError, IndexError):
        return None


def atomic_json(path: Path, value: dict):
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(encode(value) + "\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class Notifier:
    def __init__(self):
        self.address = os.environ.get("NOTIFY_SOCKET")
        if self.address and self.address.startswith("@"):
            self.address = "\0" + self.address[1:]
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) if self.address else None
        self.next_watchdog = 0.0
        self.watchdog_seconds = max(0.1, int(os.environ.get("WATCHDOG_USEC", "0")) / 2e6)

    def send(self, value: str):
        if self.socket:
            try:
                self.socket.sendto(value.encode(), self.address)
            except OSError:
                LOG.warning("systemd notification unavailable")

    def watchdog(self):
        if time.monotonic() >= self.next_watchdog:
            self.send("WATCHDOG=1")
            self.next_watchdog = time.monotonic() + self.watchdog_seconds

    def close(self):
        if self.socket:
            self.socket.close()


class Agent:
    def __init__(self, config: Config, config_path: Path | None = None, pool: SensorPool | None = None):
        self.config = config.validate()
        self.config_path = config_path
        self.pool = pool or SensorPool(config.rediscover_seconds)
        self.stop = threading.Event()
        self.reload = threading.Event()
        self.sequence = 0
        self.last_committed_sequence = 0
        self.pending: deque = deque()
        self.events: list[dict] = []
        self.dropped = 0
        self.write_failures = 0
        self.commit_ms = 0.0
        self.last_error = None
        self.last_maintenance = 0.0
        self.sensor_errors = 0
        self.sensor_timeouts = 0
        self.session = None
        self.boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()

    def _event(self, kind: str, **details):
        # All events are bounded, even when disk stays unavailable for months.
        if len(self.events) < 32:
            self.events.append({"type": kind, "details": details, "utc_ns": time.time_ns()})

    def _reload(self):
        self.reload.clear()
        if not self.config_path:
            return
        try:
            updated = load_config(self.config_path)
            if updated.data_dir != self.config.data_dir:
                raise ValueError("data_dir requires a service restart")
            if updated.fingerprint == self.config.fingerprint:
                return
            # Shrinking the buffer while degraded would silently discard pending observations.
            if updated.max_pending_cycles < len(self.pending):
                raise ValueError("pending queue exceeds new buffer size")
            previous = self.config.fingerprint
            self.config = updated
            self.pool.rediscover_seconds = updated.rediscover_seconds
            self.pool.invalidate()
            self._event("configuration_changed", previous=previous, current=updated.fingerprint)
            LOG.info("configuration reloaded")
            self._heartbeat(True)
        except (OSError, ValueError, TypeError) as exc:
            self._event("configuration_rejected", error=type(exc).__name__, message=str(exc))
            LOG.error("configuration rejected: %s", exc)

    def _heartbeat(self, running: bool):
        state = {
            "pid": os.getpid(), "pid_start_ticks": process_start_ticks(os.getpid()), "boot_id": self.boot_id,
            "session_id": self.session, "updated_utc_ns": time.time_ns(), "running": running,
            "sequence": self.sequence, "last_committed_sequence": self.last_committed_sequence,
            "pending_cycles": len(self.pending), "dropped_cycles": self.dropped,
            "write_failures": self.write_failures, "last_error": self.last_error,
            "last_commit_ms": self.commit_ms, "interval_seconds": self.config.interval_seconds,
            "sensor_errors_last_cycle": self.sensor_errors, "adapter_timeouts_last_cycle": self.sensor_timeouts,
            "config_hash": self.config.fingerprint,
        }
        try:
            atomic_json(self.config.data_dir / "health.json", state)
        except OSError as exc:
            LOG.error("health file unavailable: %s", type(exc).__name__)

    def _flush(self, store: Store):
        if time.monotonic() - self.last_maintenance > 60:
            result=maintain(store.con,self.config)
            self.last_maintenance=time.monotonic()
            if result['deleted']: self._event('retention_applied', **result)
        ensure_capacity(self.config.data_dir,self.config.max_storage_bytes,self.config.minimum_free_bytes,1024**2)
        if self.write_failures:
            # Append only once per recovery attempt; remove it if this attempt also fails.
            recovery = {"type": "storage_recovered", "utc_ns": time.time_ns(), "details": {
                "failed_attempts": self.write_failures, "dropped_cycles": self.dropped,
                "pending_cycles": len(self.pending), "previous_error": self.last_error,
            }}
        else:
            recovery = None
        first = True
        while self.pending:
            frame, config = self.pending[0]
            events = self.events + ([recovery] if recovery and first else [])
            started = time.monotonic_ns()
            store.append(self.session, frame, config, events)
            self.commit_ms = (time.monotonic_ns() - started) / 1e6
            self.pending.popleft()
            self.last_committed_sequence = frame["sequence"]
            self.events.clear()
            first = False
        self.last_error = None
        self.write_failures = 0

    def run(self, cycles: int | None = None, install_signal_handlers: bool = True) -> int:
        if cycles is not None and cycles < 1:
            raise ValueError("cycles must be positive")
        lock = WriterLock(self.config.data_dir)
        store = None
        notifier = Notifier()
        previous_handlers = {}
        reason = "signal"
        try:
            store = Store(self.config.data_dir / "telemetry.sqlite3")
            self.session = store.start(self.boot_id, self.config, inventory())
            if install_signal_handlers:
                for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
                    previous_handlers[sig] = signal.getsignal(sig)
                    signal.signal(sig, (lambda *_: self.reload.set()) if sig == signal.SIGHUP else (lambda *_: self.stop.set()))
            notifier.send("READY=1\nSTATUS=Collecting hardware telemetry")
            LOG.info("collector started session=%s interval=%ss", self.session, self.config.interval_seconds)
            next_cycle = time.monotonic()
            thermal_schedule = Periodic()
            process_schedule = Periodic()
            previous_clock = None
            while not self.stop.is_set():
                notifier.watchdog()
                if self.reload.is_set():
                    previous_config = self.config.fingerprint
                    self._reload()
                    if self.config.fingerprint != previous_config:
                        thermal_schedule = Periodic()
                        process_schedule = Periodic()
                    next_cycle = min(next_cycle, time.monotonic() + self.config.interval_seconds)
                if time.monotonic() < next_cycle:
                    self.stop.wait(min(0.5, next_cycle - time.monotonic()))
                    continue
                self.sequence += 1
                mono, utc, boot = time.monotonic_ns(), time.time_ns(), boottime_ns()
                if previous_clock:
                    old_mono, old_utc, old_boot = previous_clock
                    if abs((utc - old_utc) - (boot - old_boot)) > 2e9:
                        self._event("wall_clock_changed", difference_ns=(utc - old_utc) - (boot - old_boot))
                    if (boot - old_boot) - (mono - old_mono) > 1e9:
                        self._event("suspend_gap_detected", duration_ns=(boot - old_boot) - (mono - old_mono))
                        self.pool.invalidate()
                    if mono - old_mono > max(self.config.interval_seconds * 2, self.config.interval_seconds + self.config.sensor_timeout_seconds + 1) * 1e9:
                        self._event("collection_gap", duration_ns=mono - old_mono)
                previous_clock = mono, utc, boot
                names = [name for name in self.config.enabled_collectors if name not in ("thermal", "processes")]
                if "thermal" in self.config.enabled_collectors and thermal_schedule.due(next_cycle, self.config.thermal_interval_seconds):
                    names.append("thermal")
                if "processes" in self.config.enabled_collectors and process_schedule.due(next_cycle, self.config.process_interval_seconds):
                    names.append('processes')
                    self.pool.process_options = {'interval_seconds': self.config.process_interval_seconds,
                        'top_n': self.config.process_top_n, 'generation': self.config.fingerprint}
                results = self.pool.collect(names, self.sequence, self.config.sensor_timeout_seconds)
                self.sensor_errors = sum(1 for result in results.values() for item in result["readings"] if item["quality"] != "ok")
                self.sensor_timeouts = sum(1 for result in results.values() if result["quality"] in ("error", "timeout"))
                frame = {"sequence": self.sequence, "utc_ns": utc, "monotonic_ns": mono,
                         "boottime_ns": boot, "collectors": results,
                         "collection_ms": (time.monotonic_ns() - mono) / 1e6}
                if len(self.pending) >= self.config.max_pending_cycles:
                    self.pending.popleft()
                    self.dropped += 1
                self.pending.append((frame, self.config))
                try:
                    self._flush(store)
                except (OSError, sqlite3.Error) as exc:
                    self.write_failures += 1
                    self.last_error = f"{type(exc).__name__}: {exc}"
                    if self.write_failures == 1 or self.write_failures % 60 == 0:
                        LOG.error("storage unavailable; bounded buffer=%s: %s", len(self.pending), self.last_error)
                self._heartbeat(True)
                if cycles is not None and self.sequence >= cycles:
                    reason = "cycle_limit"
                    break
                next_cycle += self.config.interval_seconds
                if next_cycle <= time.monotonic():
                    next_cycle = time.monotonic() + self.config.interval_seconds
            # An orderly stop gets one final retry; failure remains explicitly visible.
            if self.pending:
                try:
                    self._flush(store)
                except (OSError, sqlite3.Error) as exc:
                    self.last_error = f"{type(exc).__name__}: {exc}"
            if self.pending or self.dropped:
                reason += "_with_loss"
            try:
                store.finish(self.session, reason, {"pending_cycles": len(self.pending), "dropped_cycles": self.dropped})
            except sqlite3.Error:
                LOG.exception("could not record orderly stop")
                return 1
            self._heartbeat(False)
            LOG.info("collector stopped; committed=%s pending=%s dropped=%s", self.last_committed_sequence, len(self.pending), self.dropped)
            return 1 if self.pending else 0
        finally:
            notifier.send("STOPPING=1")
            for sig, handler in previous_handlers.items():
                signal.signal(sig, handler)
            if store:
                store.close()
            self.pool.close()
            notifier.close()
            lock.close()
