from copy import deepcopy
import unittest
from visual_receipt_review import apply_visual_review, summary_equations_support


class VisualReceiptReviewTests(unittest.TestCase):
    def fixture(self):
        record={'merchant':'Unknown merchant','date':'2024-01-02','total':12.5,'status':'review',
                'source':{'local_path':'data/synthetic.png'},'ocr_engines':{'paddle':{'variants':[
                    {'quality':{'recognition_complete':True},'evidence_text':'Maple Hardware\nDate: 02/01/2024\nTOTAL $12.50'}]}}}
        visual={'state':'complete','record':{'merchant':'Maple Hardware','date':'2024-01-02','total':12.5,
                'source':record['source'],'visual_evidence':{'merchant':'Maple Hardware'}}}
        return record,visual

    def test_supported_name_is_adopted_but_not_auto_confirmed(self):
        record,visual=self.fixture();before=deepcopy(record)
        result=apply_visual_review(record,visual)
        self.assertEqual(record,before)
        self.assertEqual(result['merchant'],'Maple Hardware')
        self.assertEqual(result['status'],'review')
        self.assertEqual(result['reconciliation']['fields']['merchant']['status'],'review')
        self.assertFalse(result['confidence']['auto_confirmable'])

    def test_invented_name_is_only_a_suggestion(self):
        record,visual=self.fixture();visual['record']['merchant']='Invented Shop'
        result=apply_visual_review(record,visual)
        self.assertEqual(result['merchant'],'Unknown merchant')
        self.assertEqual(result['visual_review']['fields']['merchant']['state'],'conflict')

    def test_item_amount_and_invented_date_cannot_replace_document_fields(self):
        record,visual=self.fixture()
        record['ocr_engines']['paddle']['variants'][0]['evidence_text']+='\nItem Total: $99.00'
        visual['record'].update(total=99,date='2024-02-01')
        result=apply_visual_review(record,visual)
        self.assertEqual(result['total'],12.5)
        self.assertEqual(result['date'],'2024-01-02')

    def test_customer_and_next_service_date_are_not_corroboration(self):
        record,visual=self.fixture()
        record['ocr_engines']['paddle']['variants'][0]['evidence_text']+='\nCustomer: Example\nCustomer Industries\nNext service due: 01/02/2024'
        visual['record'].update(merchant='Customer Industries',date='2024-02-01')
        result=apply_visual_review(record,visual)
        self.assertEqual(result['merchant'],'Unknown merchant')
        self.assertEqual(result['date'],'2024-01-02')

    def test_source_hash_and_established_identity_are_preserved(self):
        record,visual=self.fixture();record['sha256']='original';visual['record']['sha256']='different'
        with self.assertRaises(ValueError):apply_visual_review(record,visual)
        visual['record']['sha256']='original'
        record['merchant']='Maple'; record['reconciliation']={'fields':{'merchant':{'status':'accepted','engines':['paddle','oxr']}}}
        self.assertEqual(apply_visual_review(record,visual)['merchant'],'Maple')

    def test_visual_printed_total_requires_two_summary_equations(self):
        text='Total=200\nplus GST:20\n$80 deposit\n$140 remain\nTOTAL INCLUSIVE OF G.S.T.'
        quote='TOTAL INCLUSIVE OF G.S.T. $220'
        self.assertTrue(summary_equations_support(text,220,quote))
        for changed in (text.replace('$140','$130'),text.replace('TOTAL INCLUSIVE OF G.S.T.',''),text.replace('plus GST:20','Item total:20')):
            self.assertFalse(summary_equations_support(changed,220,quote))
        self.assertFalse(summary_equations_support(text,220,'Sum of items $220'))
        self.assertFalse(summary_equations_support(text,220,'TOTAL INCLUSIVE OF G.S.T. $200'))

    def test_logo_reading_can_use_labelled_supplier_remittance_support(self):
        record,visual=self.fixture()
        record['ocr_engines']['paddle']['variants'][0]['evidence_text']='\n'.join(['Unclear header']*21)+'\nDirect Deposit:\nMaple Hardware Pty Ltd BSB: 123456'
        self.assertEqual(apply_visual_review(record,visual)['merchant'],'Maple Hardware')
        record['ocr_engines']['paddle']['variants'][0]['evidence_text']=record['ocr_engines']['paddle']['variants'][0]['evidence_text'].replace('Direct Deposit:','Customer:')
        self.assertEqual(apply_visual_review(record,visual)['merchant'],'Unknown merchant')

    def test_manual_override_survives_and_wrong_image_is_rejected(self):
        record,visual=self.fixture();record.update(merchant='User corrected name',status='confirmed')
        self.assertEqual(apply_visual_review(record,visual)['merchant'],'User corrected name')
        record['status']='review';visual['record']['source']={'local_path':'data/other.png'}
        with self.assertRaises(ValueError):apply_visual_review(record,visual)


if __name__=='__main__':unittest.main()
