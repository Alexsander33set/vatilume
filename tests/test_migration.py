import importlib.util
import io
import json
import os
import sqlite3
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('migration', Path(__file__).resolve().parent.parent / 'scripts/migrate_to_deb.py')
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


class MigrationEvidenceTests(unittest.TestCase):
    def test_append_preserves_prefix_but_modified_or_deleted_history_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'interface.sqlite3'
            with sqlite3.connect(path) as con:
                con.execute('CREATE TABLE tariffs(id TEXT PRIMARY KEY,price TEXT)')
                con.execute("INSERT INTO tariffs VALUES('old','1.2345')")
            baseline = migration.database_state(path)
            with sqlite3.connect(path) as con:
                con.execute("INSERT INTO tariffs VALUES('new','2.5')")
            self.assertEqual(migration.database_state(path, baseline), baseline)
            with sqlite3.connect(path) as con:
                con.execute("UPDATE tariffs SET price='3' WHERE id='old'")
            self.assertNotEqual(migration.database_state(path, baseline), baseline)
            with sqlite3.connect(path) as con:
                con.execute("DELETE FROM tariffs WHERE id='old'")
            self.assertNotEqual(migration.database_state(path, baseline), baseline)

    def test_source_refresh_is_allowed_but_original_identity_stays_fixed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'telemetry.sqlite3'
            with sqlite3.connect(path) as con:
                con.execute('CREATE TABLE sources(id TEXT PRIMARY KEY,metadata_json TEXT,first_seen_utc_ns INTEGER)')
                con.execute("INSERT INTO sources VALUES('cpu','{}',1234)")
            baseline = migration.database_state(path)
            with sqlite3.connect(path) as con:
                con.execute("UPDATE sources SET metadata_json='updated'")
            self.assertEqual(migration.database_state(path, baseline), baseline)
            with sqlite3.connect(path) as con:
                con.execute('UPDATE sources SET first_seen_utc_ns=5678')
            self.assertNotEqual(migration.database_state(path, baseline), baseline)

    def test_unexpected_schema_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'ai.sqlite3'
            with sqlite3.connect(path) as con: con.execute('CREATE TABLE history(id TEXT)')
            baseline = migration.database_state(path)
            with sqlite3.connect(path) as con: con.execute('DROP TABLE history')
            with self.assertRaises(ValueError): migration.database_state(path, baseline)

    def test_changed_key_or_limits_changes_evidence_without_exposing_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'ai-api-key').write_text('private-fixture-key')
            (path / 'health.json').write_text('{}')
            before = migration.stable_files(path)
            self.assertNotIn('private-fixture-key', str(before))
            (path / 'health.json').write_text('{"running":true}')
            self.assertEqual(migration.stable_files(path), before)
            (path / 'ai-api-key').write_text('different-fixture-key')
            self.assertNotEqual(migration.stable_files(path), before)

    def test_symlink_in_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'link').symlink_to('/etc/passwd')
            with self.assertRaises(ValueError): migration.stable_files(path)

    def test_materialized_implicit_ai_limits_must_keep_effective_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); state = root / 'state'; state.mkdir()
            config = root / 'collector.toml'; config.write_text('data_dir="state"\n')
            limits = {'enabled': True, 'per_analysis_usd': .05, 'daily_usd': 1., 'monthly_usd': 2.}
            baseline = {'configuration_hash': migration.sha(config), 'stable_files': {}, 'databases': {}, 'effective_ai': {'limits': limits}}
            with patch.object(migration, 'STATE', state), patch.object(migration, 'CONFIG', config):
                migration.preserved(baseline)
                (state / 'ai-limits.json').write_text(json.dumps(limits))
                migration.preserved(baseline)
                (state / 'ai-limits.json').write_text(json.dumps({**limits, 'enabled': False}))
                with self.assertRaisesRegex(ValueError, 'Implicit AI limits changed'): migration.preserved(baseline)

    def test_tampered_package_stops_before_system_inspection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'wrong.deb'; path.write_bytes(b'not the tested package')
            with patch.object(migration.os, 'geteuid', return_value=0):
                with self.assertRaisesRegex(ValueError, 'differs'):
                    migration.preflight(path, SimpleNamespace(pw_uid=1000))

    def test_restore_atomically_replaces_symlink_without_touching_its_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); outside = root / 'outside'; outside.write_text('untouched')
            destination = root / 'restored'; destination.symlink_to(outside)
            archive = root / 'test.tar'
            with tarfile.open(archive, 'w') as tar:
                info = tarfile.TarInfo('config'); data = b'original configuration'
                info.size = len(data); info.mode = 0o600; info.uid = os.getuid(); info.gid = os.getgid()
                tar.addfile(info, io.BytesIO(data))
            with tarfile.open(archive) as tar: migration.restore_member(tar, 'config', destination)
            self.assertFalse(destination.is_symlink())
            self.assertEqual(outside.read_text(), 'untouched')
            self.assertEqual(destination.read_bytes(), data)

    def test_restore_refuses_archive_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); archive = root / 'test.tar'
            with tarfile.open(archive, 'w') as tar:
                info = tarfile.TarInfo('bad'); info.type = tarfile.SYMTYPE; info.linkname = '/etc/passwd'; tar.addfile(info)
            with tarfile.open(archive) as tar:
                with self.assertRaises(ValueError): migration.restore_member(tar, 'bad', root / 'target')
