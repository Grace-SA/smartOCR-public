from copy import deepcopy
import subprocess
import unittest
from unittest.mock import patch

from local_visual_review import apply_local_visual_review


class LocalVisualReviewTests(unittest.TestCase):
    def fixture(self):
        record={'merchant':'Unknown merchant','date':'2024-01-02','total':12,'status':'review',
                'source':{'local_path':'data/synthetic.png'},'sha256':'source',
                'ocr_engines':{'paddle':{'variants':[{'quality':{'recognition_complete':True},
                    'evidence_text':'Maple Hardware\nDate: 02/01/2024\nTOTAL $12.00'}]}}}
        visual={'state':'complete','record':{'merchant':'Maple Hardware','date':'2024-01-02','total':12,
                 'source':record['source'],'sha256':'source','visual_evidence':{'merchant':'Maple Hardware'}}}
        return record,visual

    def test_uncertain_import_uses_bounded_local_reader_and_keeps_original(self):
        record,visual=self.fixture();before=deepcopy(record)
        with patch('local_visual_review.read_visual',return_value=visual) as reader:
            result=apply_local_visual_review(record)
        reader.assert_called_once()
        self.assertEqual(record,before)
        self.assertEqual(result['merchant'],'Maple Hardware')
        self.assertEqual(result['status'],'review')
        self.assertFalse(result['confidence']['auto_confirmable'])

    def test_model_failure_preserves_ocr_values(self):
        record,_=self.fixture()
        with patch('local_visual_review.read_visual',side_effect=subprocess.TimeoutExpired('visual',90)):
            result=apply_local_visual_review(record)
        self.assertEqual(result['merchant'],record['merchant'])
        self.assertEqual(result['visual_review']['state'],'unavailable')

    def test_manual_decisions_and_already_supported_receipts_do_not_invoke_model(self):
        record,_=self.fixture()
        with patch('local_visual_review.read_visual') as reader:
            record['status']='confirmed';apply_local_visual_review(record)
            record['status']='review';record['review_decision']={'mode':'override'};apply_local_visual_review(record)
            record.pop('review_decision')
            with patch('local_visual_review.assess_confidence',return_value={'auto_confirmable':True}):apply_local_visual_review(record)
            reader.assert_not_called()

    def test_model_can_be_disabled_without_modifying_evidence(self):
        record,_=self.fixture()
        with patch.dict('os.environ',{'SMARTOCR_VISUAL_REVIEW':'0'}),patch('local_visual_review.read_visual') as reader:
            result=apply_local_visual_review(record)
        self.assertEqual(result['visual_review']['state'],'disabled');reader.assert_not_called()


if __name__=='__main__':unittest.main()
