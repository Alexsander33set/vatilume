#!/usr/bin/env python3
"""Validate this service on the real host, preserving its committed history.

--restart-test kills only the collector's main process and checks systemd recovery.
--verify-reboot checks a saved baseline after a reboot performed by the user.
No command here initiates a PC reboot or changes system clocks/sensor controls.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from device_observability.config import load_config
from device_observability.storage import backup, encode, readonly

UNIT = "device-observability.service"
CONFIG = Path("/etc/device-observability/collector.toml")
OUTPUT = PROJECT / "var/validation"
BASELINE = OUTPUT / "reboot-baseline.json"


def properties():
    fields = ["ActiveState", "SubState", "MainPID", "NRestarts", "MemoryCurrent", "MemoryPeak", "CPUUsageNSec", "UnitFileState", "User"]
    result = subprocess.run(["systemctl", "show", UNIT, "--property=" + ",".join(fields)],
                            check=True, capture_output=True, text=True)
    return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)


def snapshot(path: Path, through_id: int | None = None):
    with closing(readonly(path)) as con:
        deadline = time.monotonic() + 30
        con.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
        con.execute("BEGIN")
        if through_id is None:
            through_id = con.execute("SELECT COALESCE(MAX(id),0) FROM samples").fetchone()[0]
        digest = hashlib.sha256()
        count = 0
        for row in con.execute("SELECT * FROM samples WHERE id<=? ORDER BY id", (through_id,)):
            digest.update(encode(dict(row)).encode() + b"\n")
            count += 1
        latest = con.execute("SELECT * FROM samples ORDER BY id DESC LIMIT 1").fetchone()
        session = con.execute("SELECT id,boot_id,end_reason FROM sessions ORDER BY started_utc_ns DESC LIMIT 1").fetchone()
        return {"through_id": through_id, "prefix_count": count, "prefix_sha256": digest.hexdigest(),
                "latest_id": latest["id"] if latest else None, "session": dict(session) if session else None,
                "latest_sample_session_id": latest["session_id"] if latest else None,
                "schema_version": con.execute("PRAGMA user_version").fetchone()[0]}


def current_session_has_sample(state):
    return bool(state.get("session") and state.get("latest_sample_session_id") == state["session"]["id"])


def write_report(path: Path, report: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    # The report contains only operational evidence; the database backup stays 0600.
    with path.open("x") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    path.chmod(0o644)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--restart-test", action="store_true")
    mode.add_argument("--verify-reboot", action="store_true")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise PermissionError("run with sudo in your own terminal; the dedicated service owns its data")
    config = load_config(CONFIG)
    database = config.data_dir / "telemetry.sqlite3"
    before_props = properties()
    if before_props.get("User") != "device-observability" or before_props.get("ActiveState") != "active":
        raise RuntimeError("expected dedicated collector service is not active")
    if args.restart_test:
        before = snapshot(database)
        if not before["latest_id"]:
            raise RuntimeError("wait for a committed sample before injecting a failure")
        started = time.monotonic()
        subprocess.run(["systemctl", "kill", "--kill-who=main", "--signal=SIGKILL", UNIT], check=True)
        deadline = started + 35
        while time.monotonic() < deadline:
            props = properties()
            if props.get("ActiveState") == "active" and props.get("MainPID") != before_props["MainPID"]:
                after = snapshot(database, before["through_id"])
                if (after["session"]["id"] != before["session"]["id"]
                        and after["latest_id"] > before["latest_id"] and current_session_has_sample(after)):
                    break
            time.sleep(0.25)
        else:
            raise RuntimeError("collector did not resume durable collection after SIGKILL")
        if after["prefix_count"] != before["prefix_count"] or after["prefix_sha256"] != before["prefix_sha256"]:
            raise RuntimeError("previously committed sample prefix changed")
        with closing(readonly(database)) as con:
            recovery = con.execute("SELECT details_json FROM events WHERE session_id=? AND type='unclean_session_detected'",
                                   (after["session"]["id"],)).fetchone()
            if not recovery:
                raise RuntimeError("recovery event missing")
            integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError("database integrity check failed")
        backup_path = OUTPUT / f"service-backup-{time.time_ns()}.sqlite3"
        OUTPUT.mkdir(parents=True, exist_ok=True)
        backup(database, backup_path)
        restored = snapshot(backup_path, before["through_id"])
        if restored["prefix_sha256"] != before["prefix_sha256"]:
            raise RuntimeError("online backup did not preserve confirmed history")
        report = {"test": "real_service_sigkill_and_systemd_restart", "result": "passed",
                  "observed_utc_ns": time.time_ns(), "recovery_seconds": time.monotonic() - started,
                  "before_properties": before_props, "after_properties": props,
                  "before": before, "after": after, "committed_history_unchanged": True,
                  "integrity_check": integrity, "backup_integrity_and_prefix": "ok",
                  "backup_path": str(backup_path), "recovery_event": json.loads(recovery[0]),
                  "real_reboot_validated": False}
        if not BASELINE.exists():
            baseline = snapshot(database)
            baseline["database"] = str(database)
            baseline["recorded_utc_ns"] = time.time_ns()
            write_report(BASELINE, baseline)
        else:
            report["existing_reboot_baseline_preserved"] = True
    else:
        baseline = json.loads(BASELINE.read_text())
        if baseline["database"] != str(database):
            raise RuntimeError("configured database differs from the baseline")
        after = snapshot(database, baseline["through_id"])
        if after["session"]["boot_id"] == baseline["session"]["boot_id"]:
            raise RuntimeError("no new boot observed; real reboot remains unverified")
        current_boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        if after["session"]["boot_id"] != current_boot:
            raise RuntimeError("current boot has no collector session yet")
        if after["latest_id"] <= baseline["latest_id"] or not current_session_has_sample(after):
            raise RuntimeError("no new samples after reboot")
        if after["prefix_sha256"] != baseline["prefix_sha256"] or after["prefix_count"] != baseline["prefix_count"]:
            raise RuntimeError("pre-reboot history changed")
        with closing(readonly(database)) as con:
            integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError("database integrity check failed")
        report = {"test": "real_reboot", "result": "passed", "observed_utc_ns": time.time_ns(),
                  "baseline": baseline, "after": after, "properties": before_props,
                  "committed_history_unchanged": True, "integrity_check": integrity, "real_reboot_validated": True}
    path = OUTPUT / f"{report['test']}-{time.time_ns()}.json"
    write_report(path, report)
    print(json.dumps({"result": "passed", "test": report["test"], "report": str(path),
                      "committed_history_unchanged": True, "real_reboot_validated": report["real_reboot_validated"]}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, sqlite3.Error, subprocess.CalledProcessError) as exc:
        print(f"Validation failed: {exc}", file=sys.stderr)
        sys.exit(1)
