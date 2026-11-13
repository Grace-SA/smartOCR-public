import unittest
from unittest.mock import patch
from receipt_engine import build_report


class ReportGroundingTests(unittest.TestCase):
    records=[{'id':'TEST-ONLY-REPORT','merchant':'Example Shop','date':'2025-01-02','total':12.34,
              'currency':'AUD','category':'其他','purpose':'unknown','status':'review',
              'source':{'kind':'public_sample'}}]

    def test_unreviewed_does_not_mean_missing(self):
        with patch('receipt_engine.local_ai',return_value={'available':True,'engine':'test-only','text':'The core fields are populated and the records can be filtered.\n\nCheck flagged exceptions, then set a purpose if useful before exporting.'}) as model:
            report=build_report(self.records)
        self.assertEqual(report['summary']['missing_total'],0)
        self.assertEqual(report['summary']['missing_date'],0)
        self.assertTrue(report['ai_text'])
        self.assertIn('Unreviewed does not mean missing',model.call_args.args[0])
        self.assertEqual(report['ai_status'],'ready')

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
