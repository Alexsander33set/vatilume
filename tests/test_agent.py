import json
import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from device_observability.agent import Agent
from device_observability.config import Config
from device_observability.storage import Store, readonly
from device_observability.schedule import Periodic

ROOT = Path(__file__).resolve().parent.parent


class FakePool:
    def __init__(self, on_collect=None):
        self.on_collect = on_collect
        self.rediscover_seconds = 300

    def collect(self, names, token, timeout):
        if self.on_collect:
            self.on_collect(token)
        return {name: {"quality": "ok", "sources": [], "readings": []} for name in names}

    def close(self):
        pass

    def invalidate(self):
        pass


def wait_until(predicate, timeout=5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            result = predicate()
            if result:
                return result
        except (OSError, json.JSONDecodeError, sqlite3.Error):
            pass
        time.sleep(0.025)
    raise AssertionError("timed out waiting for collector progress")


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_thermal_schedule_uses_planned_cycles_without_jitter_drift(self):
        schedule = Periodic()
        due = [cycle for cycle in range(0, 121, 10) if schedule.due(1000.123 + cycle, 30)]
        self.assertEqual(due, [0, 30, 60, 90, 120])

    def test_slow_schedule_skips_missed_periods_without_catchup_burst(self):
        schedule = Periodic()
        self.assertTrue(schedule.due(100, 30))
        self.assertTrue(schedule.due(205, 30))
        self.assertFalse(schedule.due(210, 30))
        self.assertTrue(schedule.due(220, 30))

    def test_storage_failure_buffer_is_bounded_and_recovery_records_loss(self):
        class FlakyStore(Store):
            attempts = 0

            def append(self, *args):
                self.attempts += 1
                if self.attempts <= 3:
                    raise sqlite3.OperationalError("simulated disk unavailability")
                return super().append(*args)

        config = Config(self.directory, interval_seconds=0.1, max_pending_cycles=2, enabled_collectors=("system",))
        agent = Agent(config, pool=FakePool())
        with patch("device_observability.agent.Store", FlakyStore):
            with self.assertLogs("device_observability.agent", "ERROR"):
                self.assertEqual(agent.run(cycles=5, install_signal_handlers=False), 0)
        with closing(readonly(self.directory / "telemetry.sqlite3")) as con:
            self.assertEqual([row[0] for row in con.execute("SELECT sequence FROM samples ORDER BY id")], [3, 4, 5])
            recovered = json.loads(con.execute("SELECT details_json FROM events WHERE type='storage_recovered'").fetchone()[0])
            self.assertEqual(recovered["failed_attempts"], 3)
            self.assertEqual(recovered["dropped_cycles"], 2)
            self.assertTrue(con.execute("SELECT end_reason FROM sessions").fetchone()[0].endswith("with_loss"))
        self.assertEqual(agent.dropped, 2)

    def test_disk_reserve_preserves_existing_history_and_reports_unsaved_cycle(self):
        config = Config(self.directory, interval_seconds=0.1, enabled_collectors=("system",))
        self.assertEqual(Agent(config, pool=FakePool()).run(1, install_signal_handlers=False), 0)
        no_space = type("Usage", (), {"free": 0})()
        with patch("device_observability.agent.shutil.disk_usage", return_value=no_space):
            with self.assertLogs("device_observability.agent", "ERROR"):
                self.assertEqual(Agent(config, pool=FakePool()).run(1, install_signal_handlers=False), 1)
        with closing(readonly(self.directory / "telemetry.sqlite3")) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM samples").fetchone()[0], 1)
            self.assertEqual(con.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        health = json.loads((self.directory / "health.json").read_text())
        self.assertEqual(health["pending_cycles"], 1)
        self.assertIsNotNone(health["last_error"])

    def test_suspension_and_wall_clock_change_are_separate_events(self):
        config = Config(self.directory, interval_seconds=0.1, enabled_collectors=("system",))
        agent = Agent(config, pool=FakePool())
        # BOOTTIME includes suspension while MONOTONIC does not. Inject only
        # the clock source; never suspend or adjust the workstation clock.
        with patch("device_observability.agent.boottime_ns", side_effect=[1_000_000_000, 6_100_000_000]):
            self.assertEqual(agent.run(2, install_signal_handlers=False), 0)
        with closing(readonly(self.directory / "telemetry.sqlite3")) as con:
            kinds = [row[0] for row in con.execute("SELECT type FROM events")]
        self.assertIn("suspend_gap_detected", kinds)
        self.assertIn("wall_clock_changed", kinds)

    def test_real_cli_recovers_after_sigkill_reloads_and_stops_cleanly(self):
        config = self.directory / "collector.toml"

        def write_config(interval):
            config.write_text(f'data_dir="data"\ninterval_seconds={interval}\nenabled_collectors=["system","processes"]\n')

        write_config(0.1)
        data = self.directory / "data"
        children = []

        def start():
            child = subprocess.Popen([sys.executable, "-m", "device_observability", "--config", str(config), "run"],
                                     cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            children.append(child)
            return child

        def health():
            return json.loads((data / "health.json").read_text())

        try:
            first = start()
            old = wait_until(lambda: s if (s := health())["last_committed_sequence"] >= 2 else None)
            with closing(readonly(data / "telemetry.sqlite3")) as con:
                before = [tuple(row) for row in con.execute("SELECT id,session_id,sequence,collectors_json FROM samples ORDER BY id")]
                saved_process = json.loads(before[0][3])['processes']['context']
                self.assertEqual(saved_process['cpu_intervals'],0)
                self.assertTrue(saved_process['entries'])
            first.kill()
            first.wait(timeout=5)
            second = start()
            wait_until(lambda: s if (s := health())["session_id"] != old["session_id"] and s["last_committed_sequence"] >= 2 else None)
            write_config(0.2)
            second.send_signal(signal.SIGHUP)
            wait_until(lambda: health()["interval_seconds"] == 0.2)
            config.write_text('interval_seconds="invalid"\n')
            second.send_signal(signal.SIGHUP)

            def rejected():
                with closing(readonly(data / "telemetry.sqlite3")) as con:
                    return con.execute("SELECT COUNT(*) FROM events WHERE type='configuration_rejected'").fetchone()[0] > 0

            wait_until(rejected)
            self.assertEqual(health()["interval_seconds"], 0.2)
            second.terminate()
            self.assertEqual(second.wait(timeout=5), 0)
            with closing(readonly(data / "telemetry.sqlite3")) as con:
                after = [tuple(row) for row in con.execute("SELECT id,session_id,sequence,collectors_json FROM samples ORDER BY id LIMIT ?", (len(before),))]
                self.assertEqual(after, before)
                first_new = con.execute('SELECT collectors_json FROM samples WHERE session_id=? ORDER BY id LIMIT 1',(health()['session_id'],)).fetchone()[0]
                self.assertEqual(json.loads(first_new)['processes']['context']['cpu_intervals'],0)
                self.assertEqual(con.execute("SELECT COUNT(*) FROM events WHERE type='unclean_session_detected'").fetchone()[0], 1)
                self.assertEqual(con.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                latest = con.execute("SELECT end_reason FROM sessions ORDER BY started_utc_ns DESC LIMIT 1").fetchone()[0]
                self.assertEqual(latest, "signal")
            self.assertFalse(health()["running"])
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                child.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
