import unittest
import tempfile
from pathlib import Path
from receipt_engine import parse_date, merged_lines, summarize, extract_record, is_total_label, is_refund_transaction, ROOT

class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.image = Path(self.temp.name) / "synthetic.jpg"
        self.image.write_bytes(b"synthetic bytes used only for hashing; OCR is supplied")
    def test_australian_date_and_impossible_date(self):
        self.assertEqual(parse_date('Date 09/12/2025')[0][0],'2025-12-09')
        self.assertEqual(parse_date('Date 31/02/2025'),[])
        self.assertEqual(parse_date('18 MAY 2026')[0][0],'2026-05-18')
        self.assertEqual(parse_date('23.JAN.24')[0][0],'2024-01-23')
    def test_change_is_never_transaction_total(self):
        # These parser tests supply OCR and need no private receipt image.
        image = self.image
        ocr={'lines':[{'text':'TOTAL CHANGE 0.00','x':.1,'y':.5,'height':.02}], 'elapsed_ms':0}
        result=extract_record(image,ocr=ocr)
        self.assertIsNone(result['total'])
    def test_coles_total_for_items_is_not_item_count(self):
        image = self.image
        ocr={'lines':[{'text':'Total for 6 items: $37.62','x':.1,'y':.5,'height':.02}], 'elapsed_ms':0}
        self.assertEqual(extract_record(image,ocr=ocr)['total'],37.62)
    def test_tax_inclusive_total_but_not_tax_amount(self):
        self.assertTrue(is_total_label('Total (Incl. GST) $56.00'))
        self.assertFalse(is_total_label('GST INCLUDED IN TOTAL $3.20'))
        self.assertFalse(is_total_label('SUBTOTAL 56.00'))
    def test_refund_policy_is_not_a_refund(self):
        self.assertFalse(is_refund_transaction('KEEP RECEIPT FOR RETURN OR REFUND'))
        self.assertTrue(is_refund_transaction('Transaction type: REFUND\nTOTAL $42.00'))
        self.assertTrue(is_refund_transaction('REFUND\nTOTAL $42.00'))
    def test_missing_and_zero_and_currency(self):
        stats = summarize([{'total':None,'currency':'AUD'},{'total':0,'currency':'AUD'}, {'total':3.25,'currency':'USD'},{'total':-1.2,'currency':'AUD'}])
        self.assertEqual(stats['missing_total'],1)
        self.assertEqual(stats['currencies']['AUD']['total_cents'],-120)
        self.assertEqual(stats['currencies']['AUD']['known_count'],2)
        self.assertEqual(stats['currencies']['USD']['total_cents'],325)
    def test_columns_join_without_crossing_rows(self):
        lines=[{'text':'TOTAL','x':.1,'y':.5,'height':.02},{'text':'$37.62','x':.7,'y':.5,'height':.02},{'text':'GST $2.15','x':.1,'y':.45,'height':.02}]
        self.assertEqual(merged_lines({'lines':lines}),['TOTAL $37.62','GST $2.15'])

if __name__=='__main__': unittest.main()

