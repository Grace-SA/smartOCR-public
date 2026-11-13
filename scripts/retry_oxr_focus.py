"""Retry incomplete OXR output; no reference annotations are read."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ocr_ensemble import ROOT,CACHE,sha,run_focused_oxr
from receipt_pipeline import _evidence_content
from ocr_ensemble import normalized_output

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--manifest',default='research/validation100_manifest.json');args=parser.parse_args()
    mapping=[]
    for item in json.loads((ROOT/args.manifest).read_text()):
        path=CACHE/'oxr'/f'{item["id"]}.json'
        if not path.exists():continue
        raw=json.loads(path.read_text());text,_=_evidence_content('oxr',raw,normalized_output('oxr',raw))
        if raw.get('capped') or not text.strip():
            mapping.append({'id':item['id'],'source_path':item['local_path'],'prepared_path':str((CACHE/'oriented'/f'{item["id"]}.png').relative_to(ROOT))})
    print(json.dumps({'retry_ids':[item['id'] for item in mapping]}),flush=True)
    if mapping:print(json.dumps(run_focused_oxr(mapping)),flush=True)
