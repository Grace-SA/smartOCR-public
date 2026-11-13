"""Replay a saved experiment's image-verified OCR cache, without model inference.

This measures parsing changes, NOT fresh OCR accuracy or latency. It never
loads references, overwrites first attempts or writes the live receipt DB.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True,type=Path)
    p.add_argument('--out',required=True,type=Path)
    args=p.parse_args()
    files=sorted(args.source.glob('real*.json'))
    if not files: raise SystemExit('No source receipt records')
    args.out.mkdir(parents=True,exist_ok=False)
    metadata={'kind':'cache_only_parser_replay','source':str(args.source),'source_records':{f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in files},
              'code_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in ROOT.glob('*.py')},
              'latency':'Only replay_elapsed_s is measured; inference timing is unavailable for this route.'}
    (args.out/'experiment.json').write_text(json.dumps(metadata,indent=2))
    from receipt_pipeline import extract_ensemble_record
    from receipt_workflow import prepare_record
    for f in files:
        previous=json.loads(f.read_text());timer=time.monotonic()
        try:
            record=previous['record']
            result=prepare_record(extract_ensemble_record(ROOT/record['source']['local_path'],source=record['source'],record_id=record['id'],run_models=False,allow_detail_review=False))
            row={'id':previous['id'],'state':'complete','record':result}
        except Exception as exc:
            row={'id':previous['id'],'state':'failed','error':str(exc)}
        row['replay_elapsed_s']=time.monotonic()-timer
        (args.out/f.name).write_text(json.dumps(row,ensure_ascii=False,indent=2))
        print(row['id'],row['state'],flush=True)


if __name__=='__main__':main()
