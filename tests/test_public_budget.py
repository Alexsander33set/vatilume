import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from device_observability import ai_cost
from device_observability.ai_cost import CostLedger, DEFAULT_LIMITS


class PublicBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.ledger = CostLedger(root / 'ai-budget.json', root / 'ai-limits.json')

    def tearDown(self): self.temp.cleanup()

    def test_fresh_install_has_no_assumed_five_dollar_authorization(self):
        self.assertEqual(self.ledger.status()['authorized_total_usd'], 0)
        self.assertFalse(self.ledger.status()['limits']['enabled'])
        with self.assertRaises(ValueError): self.ledger.reserve(b'test', 512, 'no-approval')
        self.assertEqual(self.ledger.status()['usage']['total_usd'], 0)
        with self.assertRaises(ValueError): self.ledger.configure(DEFAULT_LIMITS)

    def test_explicit_budget_change_preserves_completed_and_uncertain_spend(self):
        self.ledger.configure(DEFAULT_LIMITS, cap_usd=5)
        request = self.ledger.reserve(b'test', 512, 'already-reserved')
        before = json.loads(self.ledger.path.read_text())['requests']
        self.ledger.configure(DEFAULT_LIMITS, cap_usd=3)
        self.assertEqual(json.loads(self.ledger.path.read_text())['requests'], before)
        self.assertGreater(self.ledger.status()['usage']['pending_usd'], 0)
        with self.assertRaises(ValueError):
            self.ledger.configure({**DEFAULT_LIMITS, 'enabled': False}, cap_usd=0)
        self.ledger.finish(request, {'input_tokens': 10, 'output_tokens': 10})
        self.ledger.configure(DEFAULT_LIMITS, cap_usd=4)
        self.assertGreater(self.ledger.status()['usage']['total_usd'], 0)
        self.assertEqual(self.ledger.status()['usage']['pending_usd'], 0)

    def test_existing_personal_pilot_is_not_reset_by_reading_new_version(self):
        original = {'cap_usd': 5., 'requests': [{'id':'old','utc_ms':1,'state':'completed','reserved_usd':1.,'actual_usd':.57}]}
        self.ledger.path.write_text(json.dumps(original, indent=2))
        previous = self.ledger.path.read_bytes()
        self.assertEqual(self.ledger.status()['authorized_total_usd'], 5)
        self.assertAlmostEqual(self.ledger.status()['usage']['total_usd'], .57)
        self.assertEqual(previous, self.ledger.path.read_bytes())

    def test_invalid_cumulative_limits_cannot_be_saved(self):
        for cap in (float('nan'), float('inf'), -1, 1001, True):
            with self.subTest(cap=cap), self.assertRaises(ValueError):
                self.ledger.configure(DEFAULT_LIMITS, cap_usd=cap)

    def test_interrupted_change_fails_closed_before_unpausing(self):
        self.ledger.status()
        real_write = ai_cost.atomic_json
        def fail_on_ledger(path, value):
            if path == self.ledger.path: raise OSError('synthetic interrupted write')
            real_write(path, value)
        with patch.object(ai_cost, 'atomic_json', side_effect=fail_on_ledger):
            with self.assertRaises(OSError): self.ledger.configure(DEFAULT_LIMITS, cap_usd=5)
        current = self.ledger.status()
        self.assertFalse(current['limits']['enabled'])
        self.assertEqual(current['authorized_total_usd'], 0)
        with self.assertRaises(ValueError): self.ledger.reserve(b'test', 512, 'after-failure')
