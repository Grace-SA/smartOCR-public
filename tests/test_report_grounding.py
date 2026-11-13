import unittest
from unittest.mock import patch
from receipt_engine import build_report


class ReportGroundingTests(unittest.TestCase):
    records=[{'id':'TEST-ONLY-REPORT','merchant':'Example Shop','date':'2025-01-02','total':12.34,
              'currency':'AUD','category':'其他','purpose':'unknown','status':'review',
              'source':{'kind':'public_sample'}}]

    def test_unreviewed_does_not_mean_missing(self):
        with patch('receipt_engine.local_ai',return_value={'available':True,'engine':'test-only','text':'{"action_ids":["review","purpose","export"]}'}) as model:
            report=build_report(self.records)
        self.assertEqual(report['summary']['missing_total'],0)
        self.assertEqual(report['summary']['missing_date'],0)
        self.assertTrue(report['ai_text'])
        self.assertIn('Unreviewed does not mean missing',model.call_args.args[0])
        self.assertEqual(report['ai_status'],'ready')
        self.assertEqual(report['ai_method'],'prioritised_verified_actions')

    def test_fabricated_status_counts_in_words_are_not_published(self):
        records=[{**self.records[0],'status':'confirmed'}]
        with patch('receipt_engine.local_ai',return_value={'available':True,'text':'One receipt is automatically confirmed, another is reviewed by a person.'}):
            report=build_report(records)
        self.assertEqual(report['summary']['auto_confirmed'],0)
        self.assertEqual(report['summary']['confirmed'],1)
        self.assertIsNone(report['ai_text'])

    def test_actions_must_apply_to_current_scope_and_cannot_smuggle_prose(self):
        for text in ('{"action_ids":["category"]}', '{"action_ids":["review","review"]}',
                     '{"action_ids":["export"],"text":"One automatic receipt"}', '{"action_ids":[{}]}'):
            with self.subTest(text=text),patch('receipt_engine.local_ai',return_value={'available':True,'text':text}):
                report=build_report(self.records)
                self.assertIsNone(report['ai_text'])

    def test_only_allowed_action_text_is_rendered(self):
        with patch('receipt_engine.local_ai',return_value={'available':True,'text':'{"action_ids":["export","purpose"]}'}):
            report=build_report(self.records)
        actions={a['id']:a for a in report['action_items']}
        self.assertEqual(report['ai_text'],'\n\n'.join(actions[k]['title']+'. '+actions[k]['description'] for k in ['export','purpose']))

    def test_contradictory_missing_claim_is_not_published(self):
        with patch('receipt_engine.local_ai',return_value={'available':True,'engine':'test-only','text':'All receipts have missing dates and totals.'}) as model:
            report=build_report(self.records)
        self.assertIsNone(report['ai_text'])
        self.assertIn('factual checks',report['ai_unavailable_reason'])
        self.assertEqual(report['ai_status'],'unavailable')
        self.assertEqual(model.call_count,2)
        self.assertIn('present on every receipt',report['narrative'])

    def test_missing_synonyms_and_unnecessary_categorisation_are_rejected(self):
        for text in ['Merchant, transaction date and total remain unpopulated.',
                     'The transaction dates are not recorded.',
                     'Receipt totals are blank.',
                     'There are no amounts available.',
                     'Assign a category to the uncategorised receipts.']:
            with self.subTest(text=text),patch('receipt_engine.local_ai',return_value={'available':True,'text':text}):
                report=build_report(self.records)
                self.assertEqual(report['ai_status'],'unavailable')
                self.assertIsNone(report['ai_text'])
                self.assertIn('All 1 receipts contain a merchant',' '.join(report['facts']))


if __name__=='__main__':unittest.main()
