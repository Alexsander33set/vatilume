from __future__ import annotations

import fcntl
import json
import os
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path

from . import __version__
from .config import Config

SCHEMA_VERSION = 1
SCHEMA = """
BEGIN IMMEDIATE;
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE configurations (hash TEXT PRIMARY KEY, document TEXT NOT NULL, created_utc_ns INTEGER NOT NULL);
CREATE TABLE sessions (
    id TEXT PRIMARY KEY, device_id TEXT NOT NULL, boot_id TEXT NOT NULL,
    started_utc_ns INTEGER NOT NULL, started_monotonic_ns INTEGER NOT NULL,
    ended_utc_ns INTEGER, end_reason TEXT, version TEXT NOT NULL, inventory_json TEXT NOT NULL
);
CREATE TABLE sources (id TEXT PRIMARY KEY, metadata_json TEXT NOT NULL, first_seen_utc_ns INTEGER NOT NULL);
CREATE TABLE samples (
    id INTEGER PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
    sequence INTEGER NOT NULL, utc_ns INTEGER NOT NULL, monotonic_ns INTEGER NOT NULL,
    boottime_ns INTEGER NOT NULL, config_hash TEXT NOT NULL REFERENCES configurations(hash),
    collectors_json TEXT NOT NULL, collection_ms REAL NOT NULL,
    UNIQUE(session_id, sequence)
);
CREATE INDEX samples_utc ON samples(utc_ns);
CREATE TABLE events (
    id INTEGER PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
    utc_ns INTEGER NOT NULL, type TEXT NOT NULL, details_json TEXT NOT NULL
);
CREATE INDEX events_utc ON events(utc_ns);
PRAGMA user_version=1;
COMMIT;
"""


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)


def readonly(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", timeout=2, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    return con


class WriterLock:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True, mode=0o750)
        self.file = (directory / "writer.lock").open("a+")
        try:
            fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError("another collector already owns this data directory") from None
        self.file.seek(0)
        self.file.truncate()
        self.file.write(str(os.getpid()))
        self.file.flush()

    def close(self):
        self.file.close()


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.con = sqlite3.connect(path, timeout=1, isolation_level=None)
        self.con.row_factory = sqlite3.Row
        version = self.con.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, SCHEMA_VERSION):
            self.con.close()
            raise RuntimeError(f"unsupported schema version {version}; database left unchanged")
        if version == 0 and self.con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
            self.con.close()
            raise RuntimeError("unrecognized nonempty database; refusing initialization")
        self.con.execute("PRAGMA foreign_keys=ON")
        if self.con.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower() != "wal":
            raise RuntimeError("WAL mode unavailable")
        self.con.execute("PRAGMA synchronous=FULL")
        self.con.execute("PRAGMA wal_autocheckpoint=256")
        self.con.execute("PRAGMA journal_size_limit=4194304")
        if not version:
            self.con.executescript(SCHEMA)
        self.source_documents: dict[str, str] = {}
        self.configured_storage_limit = None

    def start(self, boot_id: str, config: Config, inventory: dict) -> str:
        session = str(uuid.uuid4())
        now = time.time_ns()
        self.con.execute("BEGIN IMMEDIATE")
        try:
            row = self.con.execute("SELECT value FROM metadata WHERE key='device_id'").fetchone()
            device_id = row[0] if row else str(uuid.uuid4())
            self.con.execute("INSERT OR IGNORE INTO metadata VALUES ('device_id', ?)", (device_id,))
            previous = self.con.execute("SELECT * FROM sessions WHERE end_reason IS NULL ORDER BY started_utc_ns").fetchall()
            self.con.execute("INSERT INTO sessions VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, ?)",
                             (session, device_id, boot_id, now, time.monotonic_ns(), __version__, encode(inventory)))
            self._configuration(config, now)
            self._event(session, now, "session_started", {"boot_id": boot_id, "version": __version__})
            for old in previous:
                last = self.con.execute("SELECT id, utc_ns, sequence FROM samples WHERE session_id=? ORDER BY id DESC LIMIT 1", (old["id"],)).fetchone()
                reason = "interrupted_boot" if old["boot_id"] != boot_id else "interrupted_process"
                self.con.execute("UPDATE sessions SET end_reason=? WHERE id=?", (reason, old["id"]))
                self._event(session, now, "unclean_session_detected", {
                    "previous_session_id": old["id"], "previous_boot_id": old["boot_id"],
                    "classification": reason, "last_committed_sample": dict(last) if last else None,
                    "note": "reason for interruption unknown; detection time is not failure time",
                })
            self.con.commit()
        except BaseException:
            self.con.rollback()
            raise
        return session

    def _configuration(self, config: Config, utc_ns: int):
        self.con.execute("INSERT OR IGNORE INTO configurations VALUES (?, ?, ?)",
                         (config.fingerprint, encode(config.document()), utc_ns))

    def _event(self, session: str, utc_ns: int, kind: str, details: dict):
        self.con.execute("INSERT INTO events(session_id, utc_ns, type, details_json) VALUES (?, ?, ?, ?)",
                         (session, utc_ns, kind, encode(details)))

    def append(self, session: str, frame: dict, config: Config, events: list[dict]) -> int:
        # A physical ceiling complements the active-data guard; free pages can be reused.
        if self.configured_storage_limit != config.max_storage_bytes:
            page_size=self.con.execute('PRAGMA page_size').fetchone()[0]
            pages=max(16,config.max_storage_bytes//page_size)
            self.con.execute(f'PRAGMA max_page_count={pages}')
            self.configured_storage_limit = config.max_storage_bytes
        changed: dict[str, str] = {}
        payload = {}
        for name, result in frame["collectors"].items():
            payload[name] = {k: v for k, v in result.items() if k != "sources"}
            for item in result["sources"]:
                document = encode(item)
                if self.source_documents.get(item["id"]) != document:
                    changed[item["id"]] = document
        self.con.execute("BEGIN IMMEDIATE")
        try:
            self._configuration(config, frame["utc_ns"])
            for identity, document in changed.items():
                self.con.execute("""INSERT INTO sources VALUES (?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET metadata_json=excluded.metadata_json""",
                                 (identity, document, frame["utc_ns"]))
            cursor = self.con.execute("""INSERT INTO samples(session_id, sequence, utc_ns, monotonic_ns,
                boottime_ns, config_hash, collectors_json, collection_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (session, frame["sequence"], frame["utc_ns"], frame["monotonic_ns"], frame["boottime_ns"],
                 config.fingerprint, encode(payload), frame["collection_ms"]))
            for event in events:
                self._event(session, event.get("utc_ns", frame["utc_ns"]), event["type"], event["details"])
            self.con.commit()
            self.source_documents.update(changed)
            return cursor.lastrowid
        except BaseException:
            self.con.rollback()
            raise

    def finish(self, session: str, reason: str, details: dict):
        now = time.time_ns()
        self.con.execute("BEGIN IMMEDIATE")
        try:
            self.con.execute("UPDATE sessions SET ended_utc_ns=?, end_reason=? WHERE id=?", (now, reason, session))
            self._event(session, now, "session_stopped", {"reason": reason, **details})
            self.con.commit()
        except BaseException:
            self.con.rollback()
            raise

    def close(self):
        self.con.close()


def backup(source: Path, destination: Path):
    if source.resolve() == destination.resolve():
        raise ValueError("backup must have a different path")
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        with closing(readonly(source)) as reader, closing(sqlite3.connect(destination)) as writer:
            deadline = time.monotonic() + 60

            def progress(status, remaining, total):
                if time.monotonic() > deadline:
                    raise TimeoutError("backup deadline exceeded")

            reader.backup(writer, pages=256, progress=progress, sleep=0.05)
            writer.commit()
            result = writer.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise RuntimeError(f"backup integrity check: {result}")
    except BaseException:
        destination.unlink(missing_ok=True)
        raise

