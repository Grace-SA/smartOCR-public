import unittest
import tempfile
import json
from pathlib import Path

from receipt_identity import merchant_key
from receipt_confidence import assess_confidence
from scripts.evaluate_receipts import compare
from scripts.score_receipt_experiment import key, score
from test_confidence import fixture


class MerchantIdentityTests(unittest.TestCase):
    def test_unicode_names_remain_distinct(self):
        for left, right in [('上海商店', '北京商店'), ('Café', 'Caf'), ('東京', '大阪')]:
            self.assertNotEqual(merchant_key(left), merchant_key(right))
            self.assertFalse(compare(left, right, 'merchant'))
            self.assertNotEqual(key('merchant', left), key('merchant', right))

    def test_typography_remains_equivalent(self):
        for left, right in [('A & B', 'A and B'), ('Café', 'Cafe\u0301'), ('EXAMPLE, SHOP', 'Example Shop')]:
            self.assertEqual(merchant_key(left), merchant_key(right))
            self.assertTrue(compare(left, right, 'merchant'))

    def test_empty_names_cannot_match(self):
        for value in ['', '---', '\u0301', None, 123]:
            self.assertIsNone(merchant_key(value))
            self.assertFalse(compare(value, '---', 'merchant'))

    def test_different_unicode_evidence_cannot_auto_confirm(self):
        record = fixture()
        record['merchant'] = '上海商店'
        decision = record['reconciliation']['fields']['merchant']
        decision['value'] = record['merchant']
        for candidate in decision['evidence']:
            candidate['value'] = '北京商店'
        self.assertFalse(assess_confidence(record)['auto_confirmable'])
        for candidate in decision['evidence']:
            candidate['value'] = record['merchant']
        self.assertTrue(assess_confidence(record)['auto_confirmable'])
        decision['value'] = '北京商店'
        self.assertFalse(assess_confidence(record)['auto_confirmable'])

    def test_punctuation_only_merchant_is_not_valid(self):
        record = fixture()
        record['merchant'] = '---'
        decision = record['reconciliation']['fields']['merchant']
        decision['value'] = '---'
        for candidate in decision['evidence']:
            candidate['value'] = '---'
        self.assertFalse(assess_confidence(record)['auto_confirmable'])

    def test_pilot_scores_wrong_unicode_name_as_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            references = root / 'references.json'
            references.write_text(json.dumps([{'id': 'sample', 'merchant': '上海商店',
                                               'date': '2024-01-01', 'total': 12.50}]))
            (root / 'sample.json').write_text(json.dumps({'state': 'complete', 'record': {
                'merchant': '北京商店', 'date': '2024-01-01', 'total': 12.50,
                'status': 'auto_confirmed'}}))
            report = score(root, references)
            self.assertEqual(report['fields']['merchant']['accepted_correct'], 0)
            self.assertEqual(report['all_correct'], 0)
            self.assertEqual(report['automatic_nonmatches'], 1)
            self.assertEqual(report['scoring_policy'], 'unicode-merchant-v2-2026-11-13')
