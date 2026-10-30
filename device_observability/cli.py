from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path

from . import __version__
from .agent import Agent, process_start_ticks
from .config import load_config
from .sensors import SensorPool, inventory
from .storage import backup, readonly


def output(value):
    print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def status(directory: Path) -> dict:
    health_path = directory / "health.json"
    health = json.loads(health_path.read_text()) if health_path.exists() else {}
    current_boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    live = (health.get("boot_id") == current_boot and health.get("running") is True
            and health.get("pid_start_ticks") is not None
            and process_start_ticks(health.get("pid", -1)) == health.get("pid_start_ticks"))
    fresh = time.time_ns() - health.get("updated_utc_ns", 0) < max(60, health.get("interval_seconds", 10) * 3) * 1e9
    path = directory / "telemetry.sqlite3"
    with closing(readonly(path)) as con:
        last = con.execute("SELECT id, session_id, sequence, utc_ns, collection_ms FROM samples ORDER BY id DESC LIMIT 1").fetchone()
        session = con.execute("SELECT id, boot_id, started_utc_ns, ended_utc_ns, end_reason FROM sessions ORDER BY started_utc_ns DESC LIMIT 1").fetchone()
        result = {"version": __version__, "state": "running" if live and fresh else "stopped_or_stale",
                  "health": health, "latest_session": dict(session) if session else None,
                  "latest_sample": dict(last) if last else None,
                  "sources": con.execute("SELECT COUNT(*) FROM sources").fetchone()[0],
                  "database_bytes": path.stat().st_size,
                  "wal_bytes": Path(str(path) + "-wal").stat().st_size if Path(str(path) + "-wal").exists() else 0}
    if live and fresh and (health.get("last_error") or health.get("pending_cycles")
                           or health.get("sensor_errors_last_cycle") or health.get("adapter_timeouts_last_cycle")):
        result["state"] = "degraded"
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Local hardware telemetry collector")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--config", type=Path, default=Path(__file__).resolve().parent.parent / "config/collector.toml")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="collect until SIGTERM; SIGHUP reloads configuration")
    run.add_argument("--cycles", type=int, help="optional finite number of cycles")
    commands.add_parser("doctor", help="read available sensors once; no database writes")
    commands.add_parser("status", help="show process freshness and durable progress")
    commands.add_parser("check", help="run a read-only SQLite integrity check")
    copy = commands.add_parser("backup", help="consistent online backup; never overwrite")
    copy.add_argument("destination", type=Path)
    tail = commands.add_parser("tail", help="inspect recent raw samples")
    tail.add_argument("--limit", type=int, default=1)
    args = parser.parse_args(argv)
    os.umask(0o077)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        config = load_config(args.config)
        database = config.data_dir / "telemetry.sqlite3"
        if args.command == "run":
            return Agent(config, args.config).run(args.cycles)
        if args.command == "doctor":
            pool = SensorPool(config.rediscover_seconds)
            try:
                results = pool.collect(list(config.enabled_collectors), 1, config.sensor_timeout_seconds)
                output({"inventory": inventory(), "collectors": results})
            finally:
                pool.close()
        elif args.command == "status":
            output(status(config.data_dir))
        elif args.command == "check":
            with closing(readonly(database)) as con:
                checks = [row[0] for row in con.execute("PRAGMA integrity_check")]
                foreign = [list(row) for row in con.execute("PRAGMA foreign_key_check")]
                output({"integrity_check": checks, "foreign_key_errors": foreign,
                        "samples": con.execute("SELECT COUNT(*) FROM samples").fetchone()[0],
                        "sessions": con.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]})
                return 0 if checks == ["ok"] and not foreign else 1
        elif args.command == "backup":
            backup(database, args.destination)
            output({"backup": str(args.destination.resolve()), "integrity_check": "ok", "bytes": args.destination.stat().st_size})
        elif args.command == "tail":
            if not 1 <= args.limit <= 1000:
                raise ValueError("limit must be between 1 and 1000")
            with closing(readonly(database)) as con:
                rows = []
                for row in con.execute("SELECT * FROM samples ORDER BY id DESC LIMIT ?", (args.limit,)):
                    entry = dict(row)
                    entry["collectors"] = json.loads(entry.pop("collectors_json"))
                    rows.append(entry)
                output(rows)
        return 0
    except (OSError, ValueError, TypeError, RuntimeError, sqlite3.Error) as exc:
        logging.error("%s: %s", type(exc).__name__, exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())

