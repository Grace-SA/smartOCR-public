import argparse
import concurrent.futures
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ocr_ensemble import *

parser=argparse.ArgumentParser()
parser.add_argument('--manifest',default='research/sample_100_manifest.json')
parser.add_argument('--ids',nargs='*')
parser.add_argument('--engines',nargs='+',default=['paddle','unlimited','oxr'])
args=parser.parse_args()
manifest=json.loads((ROOT/args.manifest).read_text())
if args.ids: manifest=[r for r in manifest if r['id'] in args.ids]
if not manifest: raise RuntimeError('No source images selected')
mapping=prepare_images(manifest)
run_dir=CACHE/'runs'/f'{time.time_ns()}'
run_dir.mkdir(parents=True,exist_ok=True)
(run_dir/'input-map.json').write_text(json.dumps(mapping,indent=2,ensure_ascii=False))
(run_dir/'request.json').write_text(json.dumps({'manifest':args.manifest,'manifest_sha256':sha(ROOT/args.manifest),'ids':args.ids,'engines':args.engines},indent=2))
with concurrent.futures.ThreadPoolExecutor(max_workers=len(args.engines)) as pool:
    futures={pool.submit(run_engine,engine,mapping):engine for engine in args.engines}
    results=[]
    for future in concurrent.futures.as_completed(futures):
        try: result=future.result()
        except Exception as e: result={'engine':futures[future],'error':str(e)}
        results.append(result); print(json.dumps(result,ensure_ascii=False),flush=True)
    (CACHE/'last-run.json').write_text(json.dumps(results,indent=2))
    (run_dir/'results.json').write_text(json.dumps(results,indent=2))
    if any('error' in r for r in results): sys.exit(1)
