"""Offline candidate comparison. No references, new OCR calls or live DB writes."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from visual_receipt_review import apply_visual_review
from receipt_confidence import assess_confidence
from receipt_workflow import prepare_record


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ocr',type=Path,required=True)
    p.add_argument('--visual',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--uncertain-only',action='store_true',help='Mirror the live import routing policy')
    args=p.parse_args(); args.out.mkdir(parents=True,exist_ok=False)
    metadata={'kind':'saved_outputs_visual_reconciliation','ocr':str(args.ocr),'visual':str(args.visual),
              'code_sha256':hashlib.sha256((ROOT/'visual_receipt_review.py').read_bytes()).hexdigest(),
              'routing':'uncertain_only' if args.uncertain_only else 'all_records','sources':{}}
    for path in sorted(args.ocr.glob('real*.json')):
        source=json.loads(path.read_text()); other=args.visual/path.name
        if not other.exists(): raise ValueError('Missing visual source '+path.name)
        visual=json.loads(other.read_text())
        metadata['sources'][path.name]={'ocr_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                                      'visual_sha256':hashlib.sha256(other.read_bytes()).hexdigest()}
        if source['state']=='complete':
            record=source['record']
            if not (args.uncertain_only and assess_confidence(record)['auto_confirmable']):
                record=apply_visual_review(record,visual)
            result={'id':source['id'],'state':'complete','record':prepare_record(record)}
        else: result=source
        # Combining saved outputs is not a measured end-to-end processing run.
        result.pop('elapsed_s',None)
        (args.out/path.name).write_text(json.dumps(result,ensure_ascii=False,indent=2))
    (args.out/'experiment.json').write_text(json.dumps(metadata,indent=2))


if __name__=='__main__':main()
