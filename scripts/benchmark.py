#!/usr/bin/env python3
"""Observe the whole collector process (including reader threads), outside its loop."""
from __future__ import annotations

import argparse
import json
import os
import signal
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def observe(pid):
    base = Path(f"/proc/{pid}")
    fields = (base / "stat").read_text().rsplit(")", 1)[1].split()
    status = dict(line.split(":", 1) for line in (base / "status").read_text().splitlines())
    io = dict(line.split(":", 1) for line in (base / "io").read_text().splitlines())
    return {"monotonic": time.monotonic(), "cpu_seconds": (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK"),
            "rss_bytes": int(status["VmRSS"].split()[0]) * 1024,
            "peak_rss_bytes": int(status["VmHWM"].split()[0]) * 1024,
            "threads": int(status["Threads"]), "write_bytes": int(io["write_bytes"])}


def percentile(values, fraction):
    return sorted(values)[min(len(values) - 1, max(0, int(len(values) * fraction)))]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=1800)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=ROOT, help="Collector checkout/release to measure; reads it without modifying it")
    args = parser.parse_args()
    sys.path.insert(0, str(args.source_root.resolve()))
    from device_observability.config import load_config
    from device_observability.storage import readonly
    from device_observability.sensors import inventory
    if args.seconds < 1:
        parser.error("seconds must be at least 1")
    config = load_config(args.config)
    source_inventory = inventory()
    args.output.mkdir(parents=True, exist_ok=False)
    samples = []
    with (args.output / "agent.log").open("w") as logfile:
        process = subprocess.Popen([sys.executable, "-m", "device_observability", "--config", str(args.config.resolve()), "run"],
                                   cwd=args.source_root, stdout=logfile, stderr=logfile)
        try:
            started = time.monotonic()
            with (args.output / "resources.jsonl").open("w") as raw:
                while time.monotonic() - started < args.seconds:
                    if process.poll() is not None:
                        raise RuntimeError(f"collector exited early with {process.returncode}")
                    try:
                        sample = observe(process.pid)
                    except (FileNotFoundError, KeyError):
                        time.sleep(0.05)
                        continue
                    samples.append(sample)
                    raw.write(json.dumps(sample) + "\n")
                    raw.flush()
                    time.sleep(min(5, max(0.05, args.seconds - (time.monotonic() - started))))
        finally:
            if process.poll() is None:
                try:
                    samples.append(observe(process.pid))
                except (OSError, KeyError):
                    pass
                process.send_signal(signal.SIGTERM)
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    if len(samples) < 2 or process.returncode != 0:
        raise RuntimeError(f"benchmark incomplete, code={process.returncode}; inspect agent.log")
    elapsed = samples[-1]["monotonic"] - samples[0]["monotonic"]
    cpu = (samples[-1]["cpu_seconds"] - samples[0]["cpu_seconds"]) / elapsed * 100
    database = config.data_dir / "telemetry.sqlite3"
    con = readonly(database)
    try:
        latest = con.execute("SELECT id FROM sessions ORDER BY started_utc_ns DESC LIMIT 1").fetchone()[0]
        rows = con.execute("SELECT collection_ms, collectors_json FROM samples WHERE session_id=? ORDER BY sequence", (latest,)).fetchall()
        collection_ms = [row["collection_ms"] for row in rows]
        errors = sum(1 for row in rows for result in json.loads(row["collectors_json"]).values()
                     for reading in result["readings"] if reading["quality"] != "ok")
        timeouts = sum(1 for row in rows for result in json.loads(row["collectors_json"]).values() if result["quality"] == "timeout")
        process_contexts = [item['context'] for row in rows if (item := json.loads(row['collectors_json']).get('processes',{})).get('context')]
        health = json.loads((config.data_dir / "health.json").read_text())
        report = {
            "started_inventory": source_inventory,
            "source_root": str(args.source_root.resolve()),
            "source_unchanged_during_measurement": source_inventory["collector_source_sha256"] == inventory()["collector_source_sha256"],
            "duration_requested_s": args.seconds, "duration_observed_s": elapsed,
            "configuration": config.document(), "observations": len(samples), "cycles": len(rows),
            "cpu_percent_of_one_core": cpu, "rss_median_mib": statistics.median(x["rss_bytes"] for x in samples) / 1024**2,
            "rss_peak_mib": max(x["peak_rss_bytes"] for x in samples) / 1024**2,
            "rss_first_mib": samples[0]["rss_bytes"] / 1024**2, "rss_last_mib": samples[-1]["rss_bytes"] / 1024**2,
            "rss_after_warmup_mib": next((x["rss_bytes"] / 1024**2 for x in samples if x["monotonic"] - samples[0]["monotonic"] >= 30), None),
            "threads_max": max(x["threads"] for x in samples),
            "process_write_bytes_delta": samples[-1]["write_bytes"] - samples[0]["write_bytes"],
            "database_bytes": database.stat().st_size,
            "collection_p50_ms": statistics.median(collection_ms), "collection_p95_ms": percentile(collection_ms, 0.95),
            "reading_errors": errors, "adapter_timeouts": timeouts, "health": health,
            "integrity_check": con.execute("PRAGMA integrity_check").fetchone()[0],
            "meets_cpu_target": cpu <= 1, "meets_memory_target": max(x["peak_rss_bytes"] for x in samples) <= 80 * 1024**2,
            "scope": "collector process including threads; observer excluded; no wall energy measurement",
            'process_scans':len(process_contexts),
            'process_scan_p95_ms':percentile([item['scan_ms'] for item in process_contexts],.95) if process_contexts else None,
            'process_partial_scans':sum(bool(item['truncated'] or item['permission_denied'] or item['parse_errors']) for item in process_contexts),
            'processes_readable_max':max((item['readable'] for item in process_contexts),default=0),
            'process_payload_bytes':sum(len(json.dumps(item,separators=(',',':')).encode()) for item in process_contexts),
        }
        report['process_payload_estimated_bytes_per_day'] = (report['process_payload_bytes']/len(process_contexts)*86400/
            max(config.process_interval_seconds,config.interval_seconds)) if process_contexts else 0
        (args.output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2), flush=True)
    finally:
        con.close()


if __name__ == "__main__":
    main()
