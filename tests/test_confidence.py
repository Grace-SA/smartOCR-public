import copy
import unittest
from receipt_confidence import assess_confidence,apply_confidence


def fixture():
    record={'merchant':'Example Store','date':'2024-02-03','total':12.34,'status':'review',
            'ocr_engines':{e:{'recognition_complete':True} for e in ('paddle','unlimited','oxr')},
            'reconciliation':{'fields':{}}}
    for field in ('merchant','date','total'):
        record['reconciliation']['fields'][field]={'value':record[field],'status':'accepted','disagreement':False,'flags':[],
            'evidence':[{'engine':e,'value':record[field],'score':95,'flags':[]} for e in ('paddle','unlimited','oxr')]}
    return record


class ConfidenceTests(unittest.TestCase):
    def test_clear_independent_evidence_is_auto_confirmed(self):
        r=apply_confidence(fixture())
        self.assertEqual(r['status'],'auto_confirmed')
        self.assertEqual(r['confidence']['score'],99)
        self.assertFalse(r['confidence']['calibrated'])

    def test_repeated_views_are_one_vote(self):
        r=fixture();d=r['reconciliation']['fields']['total']
        for e,c in zip(['paddle','paddle:focus','paddle:detail:total'],d['evidence']):c['engine']=e
        self.assertFalse(assess_confidence(r)['auto_confirmable'])

    def test_capped_disagreeing_or_missing_fields_need_review(self):
        for mode in ('capped','conflict','missing','incomplete'):
            r=fixture();d=r['reconciliation']['fields']['total']
            if mode=='capped':
                for c in d['evidence'][1:]:c['flags']=['source_output_capped']
            elif mode=='conflict':d['disagreement']=True
            elif mode=='missing':r['total']=None
            else:r['ocr_engines']['oxr']['recognition_complete']=False
            self.assertEqual(apply_confidence(r)['status'],'review',mode)

    def test_zero_and_refund_are_valid_amounts(self):
        for value in [0,-7.5]:
            r=fixture();r['total']=value;r['reconciliation']['fields']['total']['value']=value
            for c in r['reconciliation']['fields']['total']['evidence']:c['value']=value
            self.assertTrue(assess_confidence(r)['auto_confirmable'])

    def test_human_override_and_reopen_are_preserved(self):
        for status,mode in [('confirmed','override'),('review','manual_reopen')]:
            r=fixture();r['status']=status;r['review_decision']={'mode':mode}
            self.assertEqual(apply_confidence(r)['status'],status)

    def test_unfamiliar_anchored_header_needs_three_complete_independent_votes(self):
        r=fixture()
        for c in r['reconciliation']['fields']['merchant']['evidence']:
            c['score']=78; c['flags']=['business_header_context']
        self.assertTrue(assess_confidence(r)['auto_confirmable'])
        r['ocr_engines']['oxr']['recognition_complete']=False
        self.assertFalse(assess_confidence(r)['auto_confirmable'])

    def test_no_answer_fields_or_generic_scores_used(self):
        r=fixture();r['benchmark']={'passed':True};r['confidence']={'score':100}
        r['reconciliation']['fields']['merchant']['evidence']=[]
        self.assertFalse(assess_confidence(r)['auto_confirmable'])


if __name__=='__main__':unittest.main()
