"""Experimental fast extraction for comparison; never auto-confirms.

One resident Paddle pass plus bounded local text AI. This is NOT a visual AI
model and cannot recover text/logos absent from OCR. The live app still uses
the three-model route. Compare correctness AND review coverage before promotion.
"""
import copy
import time
from pathlib import Path


def extract_quick_record(image_path, record_id):
    from ocr_ensemble import ROOT, prepare_images, run_engine, sha
    from receipt_pipeline import _load_variant, _engine_quality, _field_evidence
    from receipt_extraction_v2 import reconcile
    from receipt_engine import now
    from receipt_semantics import interpret
    from receipt_workflow import prepare_record
    started=time.monotonic()
    path=Path(image_path).resolve()
    mapping=prepare_images([{'id':record_id,'local_path':str(path.relative_to(ROOT))}])
    preprocessing=time.monotonic()-started
    timing=run_engine('paddle',mapping)
    prepared=ROOT/mapping[0]['prepared_path']
    variant=_load_variant('paddle',record_id,sha(prepared))
    if not variant or not variant['quality']['recognition_complete']:
        raise RuntimeError('Fast pass has no complete OCR output')
    base=reconcile([variant['candidates']])
    lines=[s for s in variant['evidence_text'].splitlines() if s.strip()]
    timer=time.monotonic();semantic=interpret(lines);semantic_s=time.monotonic()-timer
    resolved=copy.deepcopy(base)
    for field,suggestion in semantic.get('accepted',{}).items():
        # Never discard the baseline: conflict and AI evidence remain inspectable.
        resolved[field]=suggestion['value']
        resolved['fields'][field]={'value':suggestion['value'],'status':'review','disagreement':base.get(field) not in (None,suggestion['value']),
                                   'evidence':[{'engine':'paddle','value':suggestion['value'],'score':70,'evidence':suggestion['quote'],
                                                'flags':['semantic_single_engine_review']}], 'flags':['semantic_single_engine_review']}
    record={'id':record_id,'merchant':resolved.get('merchant') or 'Unknown merchant','date':resolved.get('date'),
            'total':resolved.get('total'),'currency':'AUD','category':'Uncategorised','purpose':'unknown',
            'status':'review','tags':[],'notes':'','source':{'local_path':str(path.relative_to(ROOT))},
            'sha256':sha(path),'created_at':now(),'ocr_text':variant['evidence_text'],'ocr_text_engine':'paddle',
            'field_evidence':{f:_field_evidence(f,resolved['fields'][f]) for f in ('merchant','date','total')},
            'ocr_engines':{'paddle':_engine_quality([variant],[])},'reconciliation':resolved,'base_reconciliation':base,
            'ai_field_review':semantic,'analysis_engine':'Experimental resident Paddle + grounded local AI',
            'classification_engine':'merchant rules','processing':{'elapsed_s':time.monotonic()-started,
            'preprocessing_s':preprocessing,'paddle':timing,'semantic_s':semantic_s},
            'warnings':['Experimental fast route requires review; single-engine evidence is not automatic confirmation.']}
    return prepare_record(record)
