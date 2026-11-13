import unittest
from merchant_identity import verified_supplier_candidates
from receipt_extraction_v2 import collect_candidates,reconcile
from receipt_confidence import assess_confidence


class MerchantIdentityTests(unittest.TestCase):
    def setUp(self):
        self.registry={'12345678901':{'name':'Maple Electrical Repairs Pty Ltd','source':'https://example.test/registry','verified_on':'2026-11-13'}}

    def test_verified_identity_needs_printed_name_support_and_supplier_role(self):
        text='Maple Electrical Repairs\nABN 12 345 678 901'
        result=verified_supplier_candidates(text,'paddle',self.registry)
        self.assertEqual(result[0]['value'],'Maple Electrical Repairs Pty Ltd')
        self.assertIn('external_legal_identity_requires_review',result[0]['flags'])
        for bad in ('Different Store\nABN 12 345 678 901','Customer: Example\n'+text,'Invoice To\n'+text,text.replace('901','902')):
            self.assertEqual(verified_supplier_candidates(bad,'paddle',self.registry),[])

    def test_legal_entity_resolution_cannot_auto_confirm(self):
        candidates=[]
        for engine in ('paddle','unlimited','oxr'):
            c=collect_candidates('Date: 02/01/2024\nTOTAL $12.00',engine)
            c['merchant']=verified_supplier_candidates('Maple Electrical Repairs\nABN 12 345 678 901',engine,self.registry)
            candidates.append(c)
        result=reconcile(candidates)
        record={k:result[k] for k in ('merchant','date','total')};record['reconciliation']=result
        self.assertFalse(assess_confidence(record)['auto_confirmable'])


if __name__=='__main__':unittest.main()
