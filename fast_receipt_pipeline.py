"""Experimental resident execution of the existing three-engine extraction policy.

Run in a dedicated benchmark process with SMARTOCR_RESIDENT=1. This preserves
the same primary OCR requests and confidence policy; it is not an adaptive or
AI-corrected pipeline and is not enabled in the live app by default.
"""
import os


def extract_fast_record(image_path, record_id=None):
    if os.environ.get('SMARTOCR_RESIDENT') != '1':
        raise RuntimeError('Resident benchmark requires SMARTOCR_RESIDENT=1')
    from receipt_pipeline import extract_ensemble_record
    from receipt_workflow import prepare_record
    return prepare_record(extract_ensemble_record(image_path,record_id=record_id,allow_detail_review=False))
