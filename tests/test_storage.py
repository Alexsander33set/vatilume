import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path

from device_observability.config import Config, load_config
from device_observability.storage import Store, WriterLock, backup, readonly

ROOT = Path(__file__).resolve().parent.parent


def frame(sequence=1):
    return {"sequence": sequence, "utc_ns": time.time_ns(), "monotonic_ns": time.monotonic_ns(),
            "boottime_ns": time.monotonic_ns(), "collectors": {}, "collection_ms": 1.0}


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)
        self.database = self.path / "telemetry.sqlite3"
        self.config = Config(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_committed_rows_survive_kill_during_later_transaction(self):
        # The child acknowledges a FULL commit, then writes an uncommitted row.
        # Killing at that gate exercises actual WAL rollback rather than a mocked exception.
        script = """
import sys, time
from pathlib import Path
from device_observability.config import Config
from device_observability.storage import Store
p=Path(sys.argv[1]); s=Store(p/'telemetry.sqlite3'); c=Config(p)
session=s.start('test-boot',c,{})
s.append(session,{'sequence':1,'utc_ns':1,'monotonic_ns':1,'boottime_ns':1,'collectors':{},'collection_ms':0},c,[])
s.con.execute('BEGIN IMMEDIATE')
s.con.execute("INSERT INTO events(session_id,utc_ns,type,details_json) VALUES (?,2,'uncommitted','{}')",(session,))
print('transaction_open',flush=True)
time.sleep(60)
"""
        child = subprocess.Popen([sys.executable, "-c", script, str(self.path)], cwd=ROOT,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            import selectors
            with selectors.DefaultSelector() as selector:
                selector.register(child.stdout, selectors.EVENT_READ)
                self.assertTrue(selector.select(5), "child did not reach transaction gate")
            self.assertEqual(child.stdout.readline().strip(), "transaction_open")
            child.kill()
            child.wait(timeout=5)
            store = Store(self.database)
            try:
                self.assertEqual(store.con.execute("SELECT COUNT(*) FROM samples").fetchone()[0], 1)
                self.assertEqual(store.con.execute("SELECT COUNT(*) FROM events WHERE type='uncommitted'").fetchone()[0], 0)
                new_session = store.start("test-boot", self.config, {})
                recovery = store.con.execute("SELECT details_json FROM events WHERE type='unclean_session_detected'").fetchone()
                self.assertEqual(json.loads(recovery[0])["classification"], "interrupted_process")
                store.append(new_session, frame(), self.config, [])
                self.assertEqual(store.con.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(store.con.execute("SELECT COUNT(*) FROM samples").fetchone()[0], 2)
            finally:
                store.close()
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=5)

    def test_changed_boot_is_classified_without_claiming_kernel_panic(self):
        store = Store(self.database)
        try:
            old = store.start("boot-before", self.config, {})
            store.append(old, frame(), self.config, [])
        finally:
            store.close()
        store = Store(self.database)
        try:
            store.start("boot-after-simulated", self.config, {})
            event = json.loads(store.con.execute("SELECT details_json FROM events WHERE type='unclean_session_detected'").fetchone()[0])
            self.assertEqual(event["classification"], "interrupted_boot")
            self.assertIn("unknown", event["note"])
            self.assertEqual(store.con.execute("SELECT COUNT(*) FROM samples").fetchone()[0], 1)
        finally:
            store.close()

    def test_backup_is_consistent_while_original_is_live_and_does_not_overwrite(self):
        store = Store(self.database)
        destination = self.path / "backup.sqlite3"
        try:
            session = store.start("boot", self.config, {})
            store.append(session, frame(), self.config, [])
            backup(self.database, destination)
            with closing(readonly(destination)) as con:
                self.assertEqual(con.execute("SELECT COUNT(*) FROM samples").fetchone()[0], 1)
                self.assertEqual(con.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            original_bytes = destination.read_bytes()
            with self.assertRaises(FileExistsError):
                backup(self.database, destination)
            self.assertEqual(destination.read_bytes(), original_bytes)
        finally:
            store.close()

    def test_full_disk_simulated_by_sqlite_page_limit_preserves_prior_commit(self):
        store = Store(self.database)
        try:
            session = store.start("boot", self.config, {})
            store.append(session, frame(), self.config, [])
            pages = store.con.execute("PRAGMA page_count").fetchone()[0]
            store.con.execute(f"PRAGMA max_page_count={pages}")
            with self.assertRaises(sqlite3.OperationalError):
                store.append(session, frame(2), self.config,
                             [{"type": "large", "details": {"payload": "x" * 1024 * 1024}}])
            self.assertEqual(store.con.execute("SELECT COUNT(*) FROM samples").fetchone()[0], 1)
            self.assertEqual(store.con.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            store.con.execute("PRAGMA max_page_count=100000")
            store.append(session, frame(3), self.config, [])
            self.assertEqual([r[0] for r in store.con.execute("SELECT sequence FROM samples ORDER BY id")], [1, 3])
        finally:
            store.close()

    def test_duplicate_sequence_is_rejected_atomically(self):
        store = Store(self.database)
        try:
            session = store.start("boot", self.config, {})
            store.append(session, frame(), self.config, [])
            with self.assertRaises(sqlite3.IntegrityError):
                store.append(session, frame(), self.config, [{"type": "must_rollback", "details": {}}])
            self.assertEqual(store.con.execute("SELECT COUNT(*) FROM samples").fetchone()[0], 1)
            self.assertEqual(store.con.execute("SELECT COUNT(*) FROM events WHERE type='must_rollback'").fetchone()[0], 0)
        finally:
            store.close()

    def test_long_read_snapshot_does_not_block_writer_and_checkpoint_recovers(self):
        store = Store(self.database)
        reader = None
        try:
            session = store.start("boot", self.config, {})
            store.append(session, frame(), self.config, [])
            reader = readonly(self.database)
            reader.execute("BEGIN")
            self.assertEqual(reader.execute("SELECT COUNT(*) FROM samples").fetchone()[0], 1)
            for sequence in range(2, 22):
                store.append(session, frame(sequence), self.config, [])
            self.assertEqual(reader.execute("SELECT COUNT(*) FROM samples").fetchone()[0], 1)
            self.assertEqual(store.con.execute("SELECT COUNT(*) FROM samples").fetchone()[0], 21)
            reader.rollback()
            self.assertEqual(reader.execute("SELECT COUNT(*) FROM samples").fetchone()[0], 21)
            checkpoint = store.con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            self.assertEqual(tuple(checkpoint), (0, 0, 0))
            self.assertEqual(store.con.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        finally:
            if reader:
                reader.close()
            store.close()

    def test_future_schema_is_not_downgraded(self):
        con = sqlite3.connect(self.database)
        con.execute("PRAGMA user_version=99")
        con.close()
        before = self.database.read_bytes()
        with self.assertRaises(RuntimeError):
            Store(self.database)
        self.assertEqual(self.database.read_bytes(), before)

    def test_second_writer_is_rejected(self):
        lock = WriterLock(self.path)
        try:
            with self.assertRaises(RuntimeError):
                WriterLock(self.path)
        finally:
            lock.close()

    def test_config_resolves_paths_and_rejects_typos_nan_and_boolean_intervals(self):
        path = self.path / "config.toml"
        path.write_text('data_dir="history"\ninterval_seconds=10\n')
        self.assertEqual(load_config(path).data_dir, self.path / "history")
        for text in ('interval_second=5', 'interval_seconds=nan', 'interval_seconds=true', 'enabled_collectors=["shell"]'):
            path.write_text(text)
            with self.assertRaises((TypeError, ValueError)):
                load_config(path)


if __name__ == "__main__":
    unittest.main()
