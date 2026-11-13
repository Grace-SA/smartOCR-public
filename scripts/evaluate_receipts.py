"""Evaluate immutable image inputs against separate visual annotations.

Reference values are read ONLY after extraction; never supplied to any model.
"""
import argparse
import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from receipt_engine import ROOT,read_json,write_json,now
from receipt_identity import merchant_key

def compare(actual,expected,field):
    if expected is None: return None
    if actual is None: return False
    if field=='merchant': return merchant_key(expected) is not None and merchant_key(actual)==merchant_key(expected)
    if field=='total': return Decimal(str(actual)).quantize(Decimal('.01'))==Decimal(str(expected)).quantize(Decimal('.01'))
    return actual==expected

def evaluate(manifest_path,references_path,output,require_three=True):
    from receipt_pipeline import extract_ensemble_record
    manifest=read_json(manifest_path,[])
    predictions=[]; extracted={}
    # Freeze every prediction before opening the independent answer file.
    for item in manifest:
        path=ROOT/item['local_path']; source={'kind':'public_sample','page_url':item.get('source_page_url') or item.get('source_url'),
            'image_url':item.get('image_url'),'license':item.get('license') or item.get('licence_status'),'currency_hint':'AUD'}
        try:
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            if item.get('sha256') and digest!=item['sha256']:
                raise ValueError('Image differs from frozen manifest')
            prediction=extract_ensemble_record(path,source,record_id=item['id'],run_models=False)
            predictions.append(prediction)
            extracted[item['id']]={'prediction':prediction,'sha256':digest}
        except Exception as exc:
            extracted[item['id']]={'error':str(exc)}
    reference_data=read_json(references_path,[])
    if isinstance(reference_data,dict):
        reference_data=reference_data['records']
        references={r['id']:{f:(r.get(f,{}).get('value') if r.get(f,{}).get('visibility')=='readable' else None)
                             for f in ['merchant','date','total']} for r in reference_data}
    else: references={r['id']:r for r in reference_data}
    results=[]
    for item in manifest:
        extraction=extracted[item['id']]; prediction=extraction.get('prediction',{})
        expected=references.get(item['id'],{})
        if expected.get('source_image_sha256') and extraction.get('sha256') and expected['source_image_sha256']!=extraction['sha256']:
            raise ValueError(f"Reference image hash mismatch: {item['id']}")
        checks={f:compare(prediction.get(f),expected.get(f),f) for f in ['merchant','date','total']}
        engines=prediction.get('ocr_engines',{})
        participating=[name for name,value in engines.items() if value.get('status')=='complete' and value.get('variants')]
        core_known=all(expected.get(f) is not None for f in checks)
        correct=core_known and all(v is True for v in checks.values())
        result={'id':item['id'],'expected':{f:expected.get(f) for f in checks},
            'actual':{f:prediction.get(f) for f in checks},'field_matches':checks,'reference_core_complete':core_known,
            'engines':participating,'all_three_available':len(participating)==3,
            'passed':bool(correct and (len(participating)==3 or not require_three)),
            'field_evidence':prediction.get('field_evidence',{}),'warnings':prediction.get('warnings',[])}
        if extraction.get('error'): result['error']=extraction['error']
        results.append(result)
    field_scores={field:{'correct':sum(r.get('field_matches',{}).get(field) is True for r in results),
                        'reference_available':sum(r.get('field_matches',{}).get(field) is not None for r in results)} for field in ['merchant','date','total']}
    report={'created_at':now(),'manifest_path':str(Path(manifest_path).relative_to(ROOT)),
            'manifest_sha256':hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest(),
            'scoring_policy':'unicode-merchant-v2-2026-11-13', 'reference_sha256':hashlib.sha256(Path(references_path).read_bytes()).hexdigest(),
            'count':len(manifest),'passed':sum(r['passed'] for r in results),'failed':sum(not r['passed'] for r in results),
            'core_reference_complete':sum(r.get('reference_core_complete',False) for r in results),
            'all_three_available':sum(r.get('all_three_available',False) for r in results),'fields':field_scores,
            'criterion':'Exact date and cent amount; merchant comparison ignores case, spaces, punctuation, and treats & as and. All three actual OCR models required by default.',
            'reference_limit':'Assistant visual transcription, not an independently human-reviewed gold standard. Fixed-set agreement does not imply general 100% accuracy.',
            'results':results}
    output=Path(output); output.mkdir(parents=True,exist_ok=True)
    write_json(output/'predictions.json',predictions)
    write_json(output/'evaluation.json',report)
    print(json.dumps({k:report[k] for k in ['count','passed','failed','all_three_available','fields']},ensure_ascii=False))
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--manifest',required=True); p.add_argument('--references',required=True); p.add_argument('--output',required=True);p.add_argument('--allow-partial-engines',action='store_true')
    a=p.parse_args(); evaluate(ROOT/a.manifest,ROOT/a.references,ROOT/a.output,not a.allow_partial_engines)

