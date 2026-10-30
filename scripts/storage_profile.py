#!/usr/bin/env python3
"""Compare two storage shapes using a clearly synthetic replay of real frames.

No production writes. Temporary databases are removed after measuring their
checkpointed size. This measures persistence overhead, not future UI queries.
"""
import argparse
import json
import sqlite3
import statistics
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from device_observability.storage import encode, readonly


def profile(path, frames, count, normalized):
    connection = sqlite3.connect(path, isolation_level=None)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA wal_autocheckpoint=256")
    connection.execute("CREATE TABLE cycles(id INTEGER PRIMARY KEY,utc_ns INTEGER,monotonic_ns INTEGER,collection_ms REAL,payload TEXT)")
    if normalized:
        connection.execute("CREATE TABLE observations(cycle INTEGER,collector TEXT,metadata TEXT,PRIMARY KEY(cycle,collector)) WITHOUT ROWID")
        connection.execute("CREATE TABLE readings(cycle INTEGER,source TEXT,value INTEGER,quality TEXT,error TEXT,PRIMARY KEY(cycle,source)) WITHOUT ROWID")
        connection.execute("CREATE INDEX source_time ON readings(source,cycle)")
    elapsed = []
    cpu_before = time.process_time()
    readings_count = 0
    try:
        for index in range(count):
            frame = frames[index % len(frames)]
            collectors = json.loads(frame["collectors_json"])
            started = time.monotonic_ns()
            connection.execute("BEGIN IMMEDIATE")
            payload = None if normalized else encode(collectors)
            connection.execute("INSERT INTO cycles VALUES (?,?,?,?,?)", (index + 1, index * 10_000_000_000,
                               index * 10_000_000_000, frame["collection_ms"], payload))
            for name, result in collectors.items():
                readings_count += len(result["readings"])
                if normalized:
                    connection.execute("INSERT INTO observations VALUES (?,?,?)", (index + 1, name,
                                       encode({k: v for k, v in result.items() if k != "readings"})))
                    connection.executemany("INSERT INTO readings VALUES (?,?,?,?,?)", [
                        (index + 1, reading["source_id"], reading["value"], reading["quality"], reading.get("error"))
                        for reading in result["readings"]])
            connection.commit()
            elapsed.append((time.monotonic_ns() - started) / 1e6)
        cpu_seconds = time.process_time() - cpu_before
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        connection.close()
    return {"cycles": count, "readings": readings_count, "checkpointed_bytes": path.stat().st_size,
            "bytes_per_cycle": path.stat().st_size / count, "cpu_seconds": cpu_seconds,
            "commit_p50_ms": statistics.median(elapsed), "commit_p95_ms": sorted(elapsed)[int(len(elapsed) * .95)],
            "integrity_check": integrity}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--cycles", type=int, default=500)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 10 <= args.cycles <= 10000:
        parser.error("cycles must be between 10 and 10000")
    with closing(readonly(args.input)) as con:
        frames = con.execute("SELECT collectors_json,collection_ms FROM samples ORDER BY id LIMIT 300").fetchall()
    if not frames:
        raise RuntimeError("input has no captured frames")
    with tempfile.TemporaryDirectory(prefix="device-observability-profile-") as directory:
        report = {"scope": "synthetic replay in disposable databases; not additional real measurements",
                  "source_frame_count": len(frames), "settings": "WAL/FULL, one durable transaction per cycle",
                  "cycle_json": profile(Path(directory) / "json.sqlite3", frames, args.cycles, False),
                  "normalized_with_source_index": profile(Path(directory) / "normalized.sqlite3", frames, args.cycles, True)}
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
