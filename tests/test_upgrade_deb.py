import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from device_observability.ai_store import AIStore
from device_observability.ui_store import UIStore
from test_analysis import synthetic

ROOT=Path(__file__).resolve().parent.parent
spec=importlib.util.spec_from_file_location('upgrade_deb',ROOT/'scripts/upgrade_deb.py')
upgrade=importlib.util.module_from_spec(spec);spec.loader.exec_module(upgrade)


class UpgradePreservationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.state=self.root/'state';self.state.mkdir();synthetic(self.state)
        UIStore(self.state/'interface.sqlite3').save_tariff('1.23','2026-10-29','Synthetic upgrade tariff')
        AIStore(self.state/'ai.sqlite3')
        for name,value in {'interface-token':'a'*43,'ai-api-key':'synthetic-upgrade-key',
            'ai-budget.json':json.dumps({'cap_usd':3.,'requests':[]}),
            'ai-limits.json':json.dumps({'enabled':False,'per_analysis_usd':.05,'daily_usd':1.,'monthly_usd':2.})}.items():
            path=self.state/name;path.write_text(value);path.chmod(0o600)
        self.config=self.root/'collector.toml';self.config.write_text('data_dir='+json.dumps(str(self.state))+'\n')
        self.access=self.root/'access';self.access.mkdir();(self.access/'1000.url').write_text('http://127.0.0.1:8765/#access='+'a'*43)
        self.bundle=self.root/'backup';self.bundle.mkdir()
        self.patch=patch.multiple(upgrade,STATE=self.state,CONFIG=self.config,ACCESS=self.access);self.patch.start()

    def tearDown(self):self.patch.stop();self.temp.cleanup()

    def test_verified_snapshot_preserves_private_files_and_all_databases(self):
        before=upgrade.capture(self.bundle,'0.7.0-2')
        self.assertEqual(before['backup'],'complete_verified')
        self.assertEqual(before['archive_sha256'],upgrade.sha(self.bundle/'before.tar.gz'))
        self.assertEqual((self.bundle/'before.tar.gz').stat().st_mode&0o777,0o600)
        self.assertEqual((self.bundle/'snapshot/state/ai-api-key').read_text(),'synthetic-upgrade-key')
        upgrade.preserved(before,False)

    def test_auth_rotation_does_not_hide_other_credentials_or_history_changes(self):
        before=upgrade.capture(self.bundle,'0.7.0-2')
        (self.state/'interface-token').write_text('b'*43)
        (self.state/'interface-auth-version').write_text('2\n')
        (self.access/'1000.url').write_text('http://127.0.0.1:8765/#access='+'b'*43)
        upgrade.preserved(before,True)
        (self.state/'ai-api-key').write_text('changed-key')
        with self.assertRaisesRegex(ValueError,'Settings, key or spending changed'):upgrade.preserved(before,True)

    def test_tariff_history_modification_is_detected(self):
        before=upgrade.capture(self.bundle,'0.7.0-2')
        import sqlite3
        with sqlite3.connect(self.state/'interface.sqlite3') as con:con.execute("UPDATE tariffs SET price='9.99'")
        with self.assertRaisesRegex(ValueError,'Committed database history changed'):upgrade.preserved(before,False)

    def test_backup_rejects_symbolic_state_entries(self):
        (self.state/'unexpected').symlink_to(self.config)
        with self.assertRaises(ValueError):upgrade.capture(self.bundle,'0.7.0-2')

    def test_missing_analysis_lock_is_created_for_service_and_symlinks_are_rejected(self):
        from types import SimpleNamespace
        account=SimpleNamespace(pw_uid=os.getuid(),pw_gid=os.getgid())
        with patch.object(upgrade.pwd,'getpwnam',return_value=account):
            with upgrade.analysis_lock():pass
            path=self.state/'ai-active.lock'
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            self.assertEqual(path.stat().st_uid,os.getuid())
            path.unlink();path.symlink_to(self.config)
            with self.assertRaises(OSError):upgrade.analysis_lock()
            self.assertTrue(self.config.exists())
