import json
import os
import tempfile
import unittest
from pathlib import Path

from device_observability.ai_install import migrate_ai_state
from device_observability.ai_cost import CostLedger


class AIInstallTests(unittest.TestCase):
    def test_budget_migration_is_idempotent_preserves_native_spend_and_private_key(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, target = Path(temporary) / 'source', Path(temporary) / 'target'
            source.mkdir()
            ledger = {'cap_usd': 2.0, 'requests': [{'id': 'legacy', 'state': 'completed', 'utc_ms': 1,
                'reserved_usd': .4, 'actual_usd': .3, 'model': 'test'}]}
            (source / 'budget.json').write_text(json.dumps(ledger))
            key = source / 'openai-api-key'
            key.write_text('test-key-private-not-real')
            key.chmod(0o600)
            args = (source, target, os.getuid(), os.getgid(), os.getuid(), os.getgid())
            migrated = migrate_ai_state(*args)
            self.assertTrue(migrated['budget_preserved'])
            self.assertTrue((source / 'budget-managed.json').exists())
            self.assertEqual((target / 'ai-api-key').stat().st_mode & 0o777, 0o600)
            native = json.loads((target / 'ai-budget.json').read_text())
            native['requests'].append({**native['requests'][0], 'id': 'native', 'actual_usd': .01})
            (target / 'ai-budget.json').write_text(json.dumps(native))
            migrate_ai_state(*args)
            final = json.loads((target / 'ai-budget.json').read_text())
            self.assertEqual(len(final['requests']), 2)
            self.assertEqual(final['cap_usd'], 2.0)
            self.assertEqual(migrated['authorized_total_usd'], 2.0)
            self.assertAlmostEqual(sum(row['actual_usd'] for row in final['requests']), .31)
            self.assertEqual(key.read_text(), (target / 'ai-api-key').read_text())
            old = CostLedger(source / 'budget.json', source / 'limits.json')
            with self.assertRaises(ValueError): old.reserve(b'test', 512, 'should-not-spend-in-old-pool')

    def test_new_development_install_does_not_authorize_spending(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            result=migrate_ai_state(root/'source',root/'target',os.getuid(),os.getgid(),os.getuid(),os.getgid())
            self.assertEqual(result['authorized_total_usd'],0)
            status=CostLedger(root/'target/ai-budget.json',root/'target/ai-limits.json').status()
            self.assertFalse(status['limits']['enabled'])

    def test_existing_installed_custom_budget_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'source';target=root/'target'
            source.mkdir();target.mkdir()
            (source/'budget.json').write_text(json.dumps({'cap_usd':5.,'requests':[]}))
            (target/'ai-budget.json').write_text(json.dumps({'cap_usd':3.,'requests':[]}))
            result=migrate_ai_state(source,target,os.getuid(),os.getgid(),os.getuid(),os.getgid())
            self.assertEqual(result['authorized_total_usd'],3.)

    def test_merge_cannot_raise_authorization_to_cover_spending(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'source';target=root/'target'
            source.mkdir();target.mkdir()
            (source/'budget.json').write_text(json.dumps({'cap_usd':5.,'requests':[{'id':'old','state':'completed','utc_ms':1,'reserved_usd':.4,'actual_usd':.3}]}))
            path=target/'ai-budget.json';path.write_text(json.dumps({'cap_usd':.2,'requests':[]}))
            before=path.read_bytes()
            with self.assertRaises(ValueError):
                migrate_ai_state(source,target,os.getuid(),os.getgid(),os.getuid(),os.getgid())
            self.assertEqual(path.read_bytes(),before)
            self.assertFalse((source/'budget-managed.json').exists())
