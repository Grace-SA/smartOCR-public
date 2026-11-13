import copy
import unittest

from receipt_workflow import prepare_record, update_record, validate_changes


def automatic():
    values = {'merchant': 'Coles', 'date': '2025-01-02', 'total': 12.30, 'currency': 'AUD'}
    engines = ['paddle', 'unlimited', 'oxr']
    record = {**values, 'id': 'a', 'category': '超市与食品', 'status': 'review', 'purpose': 'unknown',
              'tags': [], 'ocr_engines': {e: {'recognition_complete': True} for e in engines},
              'reconciliation': {'fields': {k: {'value': v, 'status': 'accepted', 'disagreement': False,
                 'evidence': [{'value': v, 'engine': e, 'score': 95} for e in engines]}
                 for k, v in values.items() if k != 'currency'}}}
    return prepare_record(record)


class WorkflowTests(unittest.TestCase):
    def test_migration_only_metadata(self):
        record = automatic()
        self.assertEqual(record['status'], 'auto_confirmed')
        self.assertEqual(record['category'], 'Groceries & food')
        self.assertEqual(record['original_extraction']['total'], 12.30)
        for key in ('merchant', 'date', 'total'):
            self.assertEqual(record[key], record['reconciliation']['fields'][key]['value'])

    def test_metadata_does_not_require_reconfirmation(self):
        record = automatic()
        updated = update_record(record, {'notes': 'For my trip', 'category': 'Other'})
        self.assertEqual(updated['status'], 'auto_confirmed')
        self.assertNotIn('notes', record)
        self.assertEqual(updated['edit_history'][-1]['after']['category'], 'Other')

    def test_override_preserves_original_and_audit(self):
        record = automatic()
        updated = update_record(record, {'total': -7.50})
        self.assertEqual(updated['status'], 'confirmed')
        self.assertEqual(updated['review_decision']['mode'], 'override')
        self.assertEqual(updated['original_extraction']['total'], 12.30)
        self.assertEqual(updated['reconciliation'], record['reconciliation'])
        self.assertEqual(updated['edit_history'][-1]['before']['total'], 12.30)
        self.assertEqual(updated['edit_history'][-1]['after']['total'], -7.50)
        self.assertEqual(prepare_record(updated)['status'], 'confirmed')

    def test_manual_reopen_stays_in_queue(self):
        updated = update_record(automatic(), {'status': 'review'})
        self.assertTrue(updated['confidence']['auto_confirmable'])
        self.assertEqual(prepare_record(updated)['status'], 'review')
        self.assertEqual(update_record(updated, {'notes': 'check later'})['status'], 'review')

    def test_missing_override_and_invalid_confirmation(self):
        record = automatic()
        updated = update_record(record, {'total': None})
        self.assertEqual(updated['status'], 'review')
        with self.assertRaises(ValueError):
            update_record(updated, {'status': 'confirmed'})
        self.assertEqual(record['total'], 12.30)
        self.assertEqual(update_record(updated, {'total': 0})['status'], 'confirmed')

    def test_automatic_tags_follow_fields_and_respect_removal(self):
        r=automatic()
        self.assertIn('Month: 2025-01',r['tags'])
        r=update_record(r,{'tags':['My project']})
        self.assertEqual(r['tags'],['My project'])
        r=update_record(r,{'date':'2025-02-01','category':'Other'})
        self.assertIn('Month: 2025-02',r['tags'])
        self.assertEqual(r['category'],'Other')
        self.assertIn('My project',r['tags'])

    def test_no_automatic_confirmation_or_core_edit_via_bulk(self):
        for changes in ({'total': 1}, {'status': 'confirmed'}, {'merchant': 'Other'}):
            with self.assertRaises(ValueError): validate_changes(changes, bulk=True)
        with self.assertRaises(ValueError): update_record(automatic(), {'status': 'auto_confirmed'})

    def test_clear_date_preserves_original_and_returns_to_review(self):
        record = automatic()
        updated = update_record(record, {'date': None})
        self.assertIsNone(updated['date'])
        self.assertEqual(updated['status'], 'review')
        self.assertEqual(updated['original_extraction']['date'], '2025-01-02')
        self.assertEqual(updated['edit_history'][-1]['before']['date'], '2025-01-02')
        self.assertIsNone(updated['edit_history'][-1]['after']['date'])
        with self.assertRaises(ValueError):
            update_record(updated, {'status': 'confirmed'})
        self.assertEqual(record['date'], '2025-01-02')

    def test_reject_nonfinite_bool_wrong_types_and_invalid_date(self):
        for changes in ({'total': float('nan')}, {'total': True}, {'date': '2024-02-31'},
                        {'merchant': None}, {'tags': ['x'] * 21}, {'purpose': 'business'}, {}):
            with self.assertRaises(ValueError): update_record(automatic(), changes)


if __name__ == '__main__': unittest.main()
