"""Local image review for uncertain imports, with source-bound immutable jobs."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid

from ocr_ensemble import ROOT,CACHE,PYTHONS,environment,sha
from receipt_confidence import assess_confidence
from visual_receipt_review import apply_visual_review
from scripts.benchmark_visual_receipts import PROMPT

MODEL=ROOT/'data/models/qwen3-vl-8b-4bit'


def read_visual(record):
    original=(ROOT/record['source']['local_path']).resolve()
    prepared=(ROOT/record['preprocessing']['prepared_path']).resolve()
    if not all(p.is_relative_to(ROOT) for p in (original,prepared)):
        raise ValueError('Visual source must belong to this workspace')
    if sha(original)!=record['sha256'] or sha(prepared)!=record['preprocessing']['prepared_sha256']:
        raise ValueError('Visual source image hash changed')
    provenance=json.loads((MODEL/'smartocr-model-provenance.json').read_text())
    verification=json.loads((MODEL/'smartocr-weight-verification.json').read_text())
    if not verification or not all(v.get('matches_download_etag') and (MODEL/name).stat().st_size==v['bytes'] for name,v in verification.items()):
        raise ValueError('Verified visual model weights are unavailable')
    recipe={'source_sha256':record['sha256'],'source_local_path':record['source']['local_path'],'prepared_sha256':record['preprocessing']['prepared_sha256'],
            'prompt_sha256':hashlib.sha256(PROMPT.encode()).hexdigest(),'model':provenance,
            'worker_sha256':sha(ROOT/'scripts/visual_receipt_worker.py'),
            'parser_sha256':sha(ROOT/'scripts/benchmark_visual_receipts.py')}
    key=hashlib.sha256(json.dumps(recipe,sort_keys=True).encode()).hexdigest()
    folder=CACHE/'visual'/key;folder.mkdir(parents=True,exist_ok=True)
    for cached in sorted(folder.glob('result-*.json')):
        candidate=json.loads(cached.read_text())
        if candidate.get('recipe')==recipe and candidate.get('state')=='complete': return candidate
    attempt=uuid.uuid4().hex
    output=folder/f'result-{attempt}.json';request=folder/f'job-{attempt}.json';log=folder/f'worker-{attempt}.log'
    job={'model_path':str(MODEL),'prepared_path':str(prepared),'source_local_path':record['source']['local_path'],
         'source_sha256':record['sha256'],'recipe':recipe,'output_path':str(output)}
    request.write_text(json.dumps(job,indent=2))
    with log.open('w') as stream:
        subprocess.run([str(PYTHONS['unlimited']),str(ROOT/'scripts/visual_receipt_worker.py'),'--request',str(request)],
                       cwd=ROOT,env=environment(),stdout=stream,stderr=subprocess.STDOUT,timeout=90,check=True)
    return json.loads(output.read_text())


def apply_local_visual_review(record):
    result=deepcopy(record)
    manual=result.get('status')=='confirmed' or result.get('review_decision',{}).get('mode') in ('override','human_confirmed','manual_reopen')
    if manual or assess_confidence(result)['auto_confirmable']:
        return result
    if os.environ.get('SMARTOCR_VISUAL_REVIEW','1')=='0':
        result['visual_review']={'state':'disabled'};return result
    try:
        result=apply_visual_review(result,read_visual(result))
    except Exception as exc:
        # OCR evidence remains usable if the local optional model is unavailable.
        result['visual_review']={'state':'unavailable','reason':str(exc)[:300]}
    result['workflow_warnings']=result.get('confidence',{}).get('reasons',[])
    return result
