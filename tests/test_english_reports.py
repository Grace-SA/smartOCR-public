import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from exports import create_report_export
from receipt_engine import build_report, summarize, CATEGORIES, LEGACY_CATEGORIES


RECORDS=[
    {'id':'REPORT-ONLY-A','merchant':'One Shop','date':'2026-01-02','total':'0.00','currency':'AUD','category':'超市与食品','status':'auto_confirmed','purpose':'unknown','source':{'kind':'public_sample'}},
    {'id':'REPORT-ONLY-B','merchant':'One Shop','date':'2026-02-01','total':'-2.35','currency':'AUD','category':'Groceries & food','status':'confirmed','purpose':'personal','source':{'kind':'public_sample'}},
    {'id':'REPORT-ONLY-C','merchant':'Other Shop','date':'2026-02-03','total':12.35,'currency':'AUD','category':'Dining','status':'review','purpose':'unknown','source':{'kind':'public_sample'}},
    {'id':'REPORT-ONLY-D','merchant':'Other Shop','date':'2026-02-31','total':100,'currency':'USD','category':'Other','status':'review','purpose':'work','source':{'kind':'public_sample'}},
    {'id':'REPORT-ONLY-E','merchant':'Unknown merchant','date':None,'total':None,'currency':'EUR','category':'待分类','status':'review','purpose':'unknown','source':{'kind':'public_sample'}},
]


class EnglishReportTests(unittest.TestCase):
    def test_counts_breakdowns_currency_and_missing_are_consistent(self):
        result=summarize(RECORDS)
        self.assertEqual((result['auto_confirmed'],result['human_confirmed'],result['confirmed'],result['ready_count'],result['review_count']),(1,1,1,2,3))
        self.assertEqual(result['currencies']['AUD']['total_cents'],1000)
        self.assertEqual(result['currencies']['AUD']['ready_total_cents'],-235)
        self.assertEqual(result['currencies']['AUD']['refund_total_cents'],-235)
        self.assertEqual(result['currencies']['USD']['total_cents'],10000)
        self.assertEqual(result['currencies']['EUR']['known_count'],0)
        self.assertEqual((result['missing_total'],result['missing_date'],result['missing_merchant'],result['missing_core']),(1,2,1,2))
        self.assertEqual((result['zero_amount_count'],result['refund_count']),(1,1))
        self.assertEqual(result['categories']['Groceries & food'],2)
        self.assertEqual(result['category_breakdown'][0]['currencies']['AUD']['total_cents'],-235)
        self.assertEqual([row['month'] for row in result['monthly_breakdown']],['2026-01','2026-02'])
        self.assertEqual(result['monthly']['2026-02'],{'AUD':1000})
        self.assertEqual(result['date_range'],{'start':'2026-01-02','end':'2026-02-03'})
        self.assertEqual(LEGACY_CATEGORIES['待分类'],CATEGORIES[-1])

    def test_build_is_scope_bound_nonmutating_and_deterministic_without_ai(self):
        before=copy.deepcopy(RECORDS)
        with patch('receipt_engine.local_ai') as model:report=build_report(RECORDS[:2],use_ai=False)
        model.assert_not_called()
        self.assertEqual(RECORDS,before)
        self.assertEqual(report['record_ids'],['REPORT-ONLY-A','REPORT-ONLY-B'])
        self.assertEqual(report['summary']['count'],2)
        self.assertEqual(report['ai_status'],'not_requested')
        self.assertTrue(report['created_at'])
        self.assertTrue(report['fingerprint'])
        self.assertIn('public receipts',' '.join(report['facts']))
        self.assertIn('not one person',' '.join(report['facts']))
        self.assertFalse(any(action['id']=='review' for action in report['action_items']))
        self.assertNotEqual(report['fingerprint'],build_report(RECORDS,use_ai=False)['fingerprint'])

    def test_ai_failure_still_returns_complete_report(self):
        with patch('receipt_engine.local_ai',side_effect=OSError('Synthetic unavailable')):report=build_report(RECORDS)
        self.assertEqual(report['ai_status'],'unavailable')
        self.assertIsNone(report['ai_text'])
        self.assertIn('remain available',report['ai_unavailable_reason'])
        self.assertTrue(report['narrative'])
        self.assertEqual(len(report['merchant_breakdown']),3)
        self.assertEqual(len(report['monthly_breakdown']),2)
        self.assertEqual(report['summary']['count'],5)
        self.assertIn('total is not available',' '.join(report['facts']))

    def test_numeric_or_personal_spending_ai_is_rejected_for_public_samples(self):
        for wording in ['You spent heavily on groceries.', 'There are 5 receipts.','日期已提取。']:
            with self.subTest(wording=wording),patch('receipt_engine.local_ai',return_value={'available':True,'text':wording}):
                report=build_report(RECORDS)
                self.assertEqual(report['ai_status'],'unavailable')
                self.assertIsNone(report['ai_text'])

    def test_readable_report_exports_are_english_escaped_and_scope_bound(self):
        from pypdf import PdfReader
        with tempfile.TemporaryDirectory(prefix='receipt-report-test-') as directory:
            report=build_report(RECORDS[:2],use_ai=False)
            report['narrative']='<script>alert("test-only")</script>'
            with patch('receipt_engine.local_ai') as model:
                html=create_report_export(report,'html',Path(directory)/'report.html')
                pdf=create_report_export(report,'pdf',Path(directory)/'report.pdf')
                data=create_report_export(report,'json',Path(directory)/'report.json')
            model.assert_not_called()
            text=html.read_text()
            self.assertIn('&lt;script&gt;',text)
            self.assertNotIn('<script>',text)
            self.assertIn('REPORT-ONLY-A',text)
            self.assertNotIn('REPORT-ONLY-C',text)
            self.assertIn('Auto-confirmed',text)
            self.assertIn('Human confirmed',text)
            self.assertIn('AI commentary was not requested',text)
            pdf_text='\n'.join(page.extract_text() for page in PdfReader(pdf).pages)
            self.assertIn('Receipt insights',pdf_text)
            self.assertIn('REPORT-ONLY-A',pdf_text)
            self.assertNotIn('REPORT-ONLY-C',pdf_text)
            self.assertIn('-2.35',pdf_text)
            self.assertEqual(json.loads(data.read_text()),report)


if __name__=='__main__':unittest.main()
