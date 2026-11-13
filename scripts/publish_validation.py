"""Publish verified extraction predictions, never reference values, to the app."""
import argparse
import hashlib
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from receipt_engine import ROOT, read_json, write_json, build_report, now
from receipt_pipeline import _apply_classification


def publish(classify=True,classification_models=True):
    folder=ROOT/'research/evaluations/validation100'
    evaluation=read_json(folder/'evaluation.json',{})
    predictions=read_json(folder/'predictions.json',[])
    manifest=read_json(ROOT/'research/validation100_manifest.json',[])
    if not (evaluation.get('count')==100 and evaluation.get('passed')==100 and evaluation.get('all_three_available')==100):
        raise RuntimeError('The frozen 100-receipt acceptance set has not passed; app data was not replaced')
    digest=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
    if evaluation['manifest_sha256']!=digest(ROOT/'research/validation100_manifest.json') or evaluation['reference_sha256']!=digest(ROOT/'research/validation100_reference.json'):
        raise RuntimeError('Evaluation inputs changed; evaluate again before publication')
    if len(predictions)!=100 or {r['id'] for r in predictions}!={r['id'] for r in manifest}:
        raise RuntimeError('Predictions do not cover the fixed 100 images')
    by_id={r['id']:r for r in evaluation['results']}
    for record in predictions:
        core={field:record.get(field) for field in ('merchant','date','total')}
        if core!=by_id[record['id']]['actual'] or record.get('ensemble_status')!='complete':
            raise RuntimeError('Predictions differ from the evaluated output')
        if classify:
            _apply_classification(record,allow_model=classification_models)
            if core!={field:record.get(field) for field in core}:
                raise RuntimeError('Classification attempted to change an extracted fact')
        record['benchmark']={'set':'validation100','passed':True,'evaluation_manifest_sha256':evaluation['manifest_sha256'],
                             'scope':['merchant','date','total'],'reference_method':'assistant visual transcription; not independent human review'}
        print(record['id'],record.get('classification_engine'),flush=True)
    database=ROOT/'data/receipts.json'
    previous=read_json(database,[])
    stamp=now().replace(':','').replace('+','_')
    if database.exists():
        backup=ROOT/'data/snapshots'/f'receipts-before-validation-{stamp}.json'
        backup.parent.mkdir(parents=True,exist_ok=True); backup.write_bytes(database.read_bytes())
    # Keep any photographs the user has independently imported while tests run.
    retained=[r for r in previous if r.get('source',{}).get('kind')!='public_sample']
    dataset=predictions+retained
    write_json(ROOT/'data/validation100_receipts.json',predictions)
    write_json(database,dataset)
    write_json(ROOT/'data/sample_report.json',build_report(dataset))
    print(f'Published {len(predictions)} validated samples; retained {len(retained)} user records',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--skip-classification',action='store_true')
    parser.add_argument('--cached-classification',action='store_true',help='Reuse completed classification without new per-receipt AI calls')
    args=parser.parse_args()
    publish(not args.skip_classification,not args.cached_classification)
