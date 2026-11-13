"""Retry unresolved image evidence with a deterministic alternate pixel view.

No reference annotations are read. Previous images, metadata and raw model
outputs are archived together before the current detail view is replaced.
"""
import argparse
import concurrent.futures
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ocr_ensemble import ROOT,CACHE,sha
from receipt_pipeline import extract_ensemble_record
from receipt_detail_views import prepare_detail
from scripts.run_detail_reviews import run_engine_details


def prepare_retries(manifest,ids=None,fields=None,variant='gray'):
    requests=[]
    for item in manifest:
        rid=item['id']
        if ids and rid not in ids: continue
        record=extract_ensemble_record(ROOT/item['local_path'],record_id=rid,run_models=False)
        for field,review in record.get('detail_evidence',{}).items():
            if fields and field not in fields: continue
            if review.get('applied'): continue
            base=(record.get('base_reconciliation') or record['reconciliation'])['fields'][field]
            if base.get('value') is not None and not base.get('disagreement'): continue
            image=CACHE/'detail'/field/'images'/f'{rid}.png'
            metadata=image.with_suffix('.detail.json')
            if metadata.exists() and json.loads(metadata.read_text()).get('variant')==variant:
                requests.append({'id':rid,'field':field,'path':str(image),'sha256':sha(image),'trigger':'reuse_alternate_view'})
                continue
            if image.exists():
                archive=CACHE/'detail_attempts'/field/rid/sha(image)
                archive.mkdir(parents=True,exist_ok=True)
                shutil.copy2(image,archive/'image.png')
                if metadata.exists():shutil.copy2(metadata,archive/'image.detail.json')
                for engine in ('paddle','unlimited','oxr'):
                    raw=CACHE/'detail'/field/engine/f'{rid}.json'
                    if raw.exists():shutil.copy2(raw,archive/f'{engine}.json')
            source=CACHE/'oriented'/f'{rid}.png'
            paddle=json.loads((CACHE/'paddle'/f'{rid}.json').read_text())
            meta=prepare_detail(source,paddle,field,image,variant=variant)
            requests.append({'id':rid,'field':field,'path':str(image),'sha256':meta['output_sha256'],'trigger':'unresolved_detail_evidence'})
    return requests


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--manifest',default='research/validation100_manifest.json')
    p.add_argument('--ids',nargs='*');p.add_argument('--fields',nargs='*')
    p.add_argument('--variant',choices=['gray','contrast'],default='gray')
    p.add_argument('--engines',nargs='+',choices=['paddle','unlimited','oxr'],default=['paddle','unlimited','oxr'])
    args=p.parse_args()
    requests=prepare_retries(json.loads((ROOT/args.manifest).read_text()),args.ids,args.fields,args.variant)
    print(json.dumps({'alternate_detail_views':len(requests),'ids':[r['id'] for r in requests]}),flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(args.engines)) as pool:
        futures=[pool.submit(run_engine_details,e,requests) for e in args.engines]
        for future in concurrent.futures.as_completed(futures):future.result()
