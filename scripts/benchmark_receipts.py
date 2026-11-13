"""Record first attempts on a local development manifest without touching the app DB.

The manifest contains images only; reference answers are loaded by the separate scorer.
Use an explicit new --out for each experiment. Existing attempts are never replaced.
"""
import argparse
import hashlib
import json
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--route', choices=['ensemble', 'resident', 'quick-ai'], default='ensemble')
    args = parser.parse_args()
    from receipt_pipeline import extract_ensemble_record
    from receipt_workflow import prepare_record
    manifest = json.loads(args.manifest.read_text())
    args.out.mkdir(parents=True, exist_ok=True)
    metadata = args.out/'experiment.json'
    if metadata.exists():
        raise SystemExit('An experiment already exists here; first attempts are immutable.')
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in ROOT.glob('*.py')}
    hashes.update({str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in (ROOT/'scripts').iterdir() if p.suffix in ('.py', '.swift')})
    metadata.write_text(json.dumps({'manifest_sha256': hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
                                    'code_sha256': hashes, 'route': args.route, 'hardware': platform.platform(),
                                    'timing': 'wall time including preprocessing, model startup, reconciliation and optional classification; no downloads or reference annotation',
                                    'samples': len(manifest), 'cache': 'unique experiment-specific IDs'}, indent=2))
    started = time.monotonic()
    rows = []
    for item in manifest:
        rid = item['id']
        record_id = args.out.name.replace('-', '_')+'_'+rid
        timer = time.monotonic()
        try:
            if args.route == 'quick-ai':
                from quick_receipt_pipeline import extract_quick_record
                result = extract_quick_record(ROOT/item['local_path'], record_id=record_id)
            elif args.route == 'resident':
                from fast_receipt_pipeline import extract_fast_record
                result = extract_fast_record(ROOT/item['local_path'], record_id=record_id)
            else:
                result = prepare_record(extract_ensemble_record(ROOT/item['local_path'], record_id=record_id, allow_detail_review=False))
            row = {'id': rid, 'state': 'complete', 'record': result}
        except Exception as exc:
            row = {'id': rid, 'state': 'failed', 'error': str(exc)}
        row['elapsed_s'] = time.monotonic()-timer
        (args.out/f'{rid}.json').write_text(json.dumps(row, ensure_ascii=False, indent=2))
        rows.append({k: v for k, v in row.items() if k != 'record'})
        (args.out/'progress.json').write_text(json.dumps({'completed': len(rows), 'total': len(manifest), 'elapsed_s': time.monotonic()-started, 'rows': rows}, indent=2))
        print(rid, row['state'], round(row['elapsed_s'], 2), flush=True)
    print('complete', len(rows), round(time.monotonic()-started, 2), flush=True)


if __name__ == '__main__':
    main()
