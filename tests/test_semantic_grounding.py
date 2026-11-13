import unittest
import json
from receipt_semantics import parse_suggestion, interpret


class SemanticGroundingTests(unittest.TestCase):
    def test_invented_amount_and_brand_rejected(self):
        result=parse_suggestion(json.dumps({'merchant':{'value':'Invented Brand','line_ids':[0]},'total':{'value':32.5,'line_ids':[1]}}),['Actual Shop','TOTAL $12.50'])
        self.assertFalse(result['accepted']);self.assertEqual(set(result['rejected']),{'merchant','total'})

    def test_exact_multiline_name_and_negative_amount_preserved(self):
        result=parse_suggestion(json.dumps({'merchant':{'value':'Example Shop Pty Ltd','line_ids':[0,1]},'total':{'value':-12.5,'line_ids':[2]}}),['Example Shop','Pty Ltd','REFUND -12.50'])
        self.assertEqual(result['accepted']['total']['value'],-12.5)
        self.assertFalse(result['accepted']['merchant']['automatic_confirmation'])

    def test_invalid_indices_and_missing_date_do_not_create_facts(self):
        result=parse_suggestion(json.dumps({'merchant':{'value':'Shop','line_ids':[-1]},'date':None,'total':{'value':2,'line_ids':[True]}}),['Shop'])
        self.assertFalse(result['accepted'])

    def test_unavailable_model_is_explicit(self):
        result=interpret(['TOTAL 12.50'],lambda *a,**k:{'available':False,'reason':'disabled'})
        self.assertFalse(result['available']);self.assertEqual(result['reason'],'disabled')

    def test_available_model_with_invalid_shape_is_not_validated(self):
        result=interpret(['TOTAL 12.50'],lambda *a,**k:{'available':True,'text':'{"total":12.50}'})
        self.assertTrue(result['available']);self.assertFalse(result['validated'])
        self.assertEqual(result['rejected']['total'],'Invalid field object')

    def test_wrong_citation_cannot_support_an_otherwise_visible_amount(self):
        result=interpret(['131 Church St','TOTAL 19.00'],lambda *a,**k:{'available':True,'text':'{"total":{"value":19,"line_ids":[0]}}'})
        self.assertFalse(result['validated']);self.assertFalse(result['accepted'])


if __name__=='__main__':unittest.main()
