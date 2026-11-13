"""First-pass timing runner. Never opens references or changes frozen rules."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'research/blind100'
PYTHON=os.environ.get('RECEIPT_PYTHON',str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3'))

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def check_freeze():
    frozen=BASE/'frozen_app';lock=json.loads((BASE/'freeze.json').read_text())
    for item in lock['files']:
        if digest(frozen/item['path'])!=item['sha256']:raise RuntimeError('Frozen code changed: '+item['path'])
    confidence=json.loads((BASE/'confidence_freeze.json').read_text())
    if digest(BASE/'confidence_policy.py')!=confidence['sha256']:raise RuntimeError('Frozen confidence policy changed')
    for item in json.loads((BASE/'external_inputs.json').read_text())['external_files']:
        if digest(Path(item['path']))!=item['sha256']:raise RuntimeError('External model runner or manifest changed: '+item['path'])
    return frozen,lock

def run(manifest_path,timeout=600):
    frozen,lock=check_freeze()
    manifest=json.loads(manifest_path.read_text())
    if len({item['id'] for item in manifest})!=len(manifest):raise ValueError('Duplicate selected IDs')
    for folder in ('runs','predictions','jobs'):(BASE/folder).mkdir(parents=True,exist_ok=True)
    for item in manifest:
        item={**item,'local_path':item.get('local_path') or item.get('path')}
        frozen,lock=check_freeze()
        source=ROOT/item['local_path'];sha=digest(source)
        if sha!=item['sha256'] or sha in lock['excluded_image_sha256']:raise RuntimeError('Changed or previously used input: '+item['id'])
        metadata=BASE/'runs'/(item['id']+'.json')
        if metadata.exists():
            previous=json.loads(metadata.read_text())
            if previous['image_sha256']!=sha:raise RuntimeError('Cannot replace an already tested input')
            print(json.dumps({'id':item['id'],'state':'first_attempt_already_recorded'}),flush=True);continue
        destination=frozen/item['local_path'];destination.parent.mkdir(parents=True,exist_ok=True)
        if destination.exists() and digest(destination)!=sha:raise RuntimeError('Frozen input changed')
        if not destination.exists():shutil.copy2(source,destination)
        job=BASE/'jobs'/(item['id']+'.json')
        job.write_text(json.dumps({'id':item['id'],'local_path':item['local_path'],'sha256':sha}))
        prediction=BASE/'predictions'/(item['id']+'.json');log=BASE/'runs'/(item['id']+'.log')
        started=time.monotonic();at=datetime.now(timezone.utc).isoformat();timed_out=False
        with log.open('w') as output:
            process=subprocess.Popen([PYTHON,str(ROOT/'scripts/blind_worker.py'),'--frozen-root',str(frozen),'--item',str(job),'--out',str(prediction)],
                cwd=frozen,stdout=output,stderr=subprocess.STDOUT,start_new_session=True,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
            try:code=process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out=True;os.killpg(process.pid,signal.SIGTERM)
                try:code=process.wait(timeout=10)
                except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);code=process.wait()
        elapsed=round(time.monotonic()-started,4)
        run={'id':item['id'],'image_sha256':sha,'started_at':at,'wall_seconds':elapsed,'returncode':code,'timed_out':timed_out,
             'timeout_seconds':timeout,'first_attempt':True,'prediction_available':prediction.exists(),'log':str(log.relative_to(ROOT)),
             'classification_included':False,'cache_policy':'New image IDs and empty frozen cache; only existing automatic retry logic allowed'}
        metadata.write_text(json.dumps(run,indent=2))
        print(json.dumps(run),flush=True)
    check_freeze()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--manifest',default='research/blind100/manifest.json');p.add_argument('--timeout',type=int,default=600)
    a=p.parse_args();run(ROOT/a.manifest,a.timeout)
