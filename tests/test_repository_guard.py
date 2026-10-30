import importlib.util
import unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location('repository_guard',Path(__file__).resolve().parent.parent/'scripts/check_repository.py')
guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)


class RepositoryGuardTests(unittest.TestCase):
    def test_private_paths_are_rejected_even_when_empty(self):
        for path in ('var/backups/archive.tar.zst','.aws/config','frontend/node_modules/x.js','.env.production','config/ai-api-key','data.sqlite3-wal','backend/static/index.html','docs/validation/report.json'):
            self.assertTrue(guard.findings(path,b''),path)
        self.assertFalse(guard.findings('.env.example',b'MODEL=example'))

    def test_patterns_and_exact_local_values_are_blocked_without_echoing_them(self):
        samples=[b'sk-'+b'proj-'+b'Abc123xyz'*10,b'ghp_'+b'A'*40,b'-----BEGIN '+b'PRIVATE KEY-----',b'https://' + b'account:credential@' + b'example.invalid']
        for value in samples:
            reasons=guard.findings('example.py',value)
            self.assertTrue(reasons)
            self.assertNotIn(value.decode(),str(reasons))
        self.assertEqual(guard.findings('example.py',b'opaque-local-capability',[b'opaque-local-capability']),['local credential/capability value'])

    def test_source_and_synthetic_test_labels_are_allowed(self):
        self.assertFalse(guard.findings('tests/test_web.py',b'test-only-private-key-not-network'))
        self.assertFalse(guard.findings('docs/IA-INTERFACE.md',b'openai-api-key is a private local file'))
