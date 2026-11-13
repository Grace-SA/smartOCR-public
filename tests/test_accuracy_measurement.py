import json
from pathlib import Path
import tempfile
import unittest

from receipt_confidence import assess_confidence
from scripts.score_receipt_experiment import score
from scripts.benchmark_visual_receipts import parse_response


class AccuracyMeasurementTests(unittest.TestCase):
    def test_failed_inference_is_not_a_correct_abstention(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            ref=p/'reference.json';ref.write_text(json.dumps([{'id':'sample','merchant':None,'date':None,'total':None}]))
            (p/'sample.json').write_text(json.dumps({'state':'failed','error':'timeout'}))
            result=score(p,ref)
            self.assertEqual(result['completed'],0)
            self.assertTrue(all(f['correct_abstentions']==0 and f['unprocessed_controls']==1 for f in result['fields'].values()))
            self.assertIsNone(result['timing_s']['sum'])

    def test_english_unknown_placeholder_is_missing(self):
        confidence=assess_confidence({'merchant':'Unknown merchant','date':'2024-01-01','total':10})
        self.assertIn('Missing or invalid merchant',confidence['fields']['merchant']['reasons'])

    def test_partial_debug_fields_of_failed_job_do_not_count_as_correct(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);fields={'merchant':'Maple','date':'2024-01-02','total':12}
            ref=p/'reference.json';ref.write_text(json.dumps([{'id':'sample',**fields}]))
            (p/'sample.json').write_text(json.dumps({'state':'failed','record':{**fields,'status':'auto_confirmed'}}))
            result=score(p,ref)
            self.assertEqual(result['all_correct'],0)
            self.assertEqual(result['automatic_count'],0)

    def test_visual_response_rejects_missing_proof_invalid_dates_and_boolean_amounts(self):
        base={'merchant':None,'date':None,'total':None}
        for patch in ({'total':True,'total_evidence':'TOTAL true'},
                      {'total':12}, {'date':'2024-02-31','date_evidence':'31/02/2024'},
                      {'merchant':123,'merchant_evidence':'123'}):
            with self.subTest(patch=patch),self.assertRaises(ValueError):
                parse_response(json.dumps({**base,**patch}))

    def test_visual_response_preserves_missing_fields_and_refund_sign(self):
        result=parse_response(json.dumps({'merchant':None,'date':None,'total':-12.5,'total_evidence':'Refund Total -12.50'}))
        self.assertEqual(result['total'],-12.5)
        self.assertIsNone(result['merchant'])

    def test_australian_date_format_can_be_normalized_but_not_completed(self):
        result=parse_response(json.dumps({'merchant':None,'date':'22/03/23','date_evidence':'22/03/23','total':None}))
        self.assertEqual(result['date'],'2023-03-22')
        with self.assertRaises(ValueError):parse_response(json.dumps({'merchant':None,'date':'22/03','date_evidence':'22/03','total':None}))


if __name__=='__main__':unittest.main()
