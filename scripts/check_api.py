"""Integration test on an isolated copy of real records; never changes the workspace data."""
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from receipt_engine import read_json,write_json
TEST=ROOT/'output/qa/api-test'
TEST.mkdir(parents=True,exist_ok=True)
DATABASE=TEST/'receipts.json'
shutil.copyfile(ROOT/'data/receipts.json',DATABASE)
with socket.socket() as sock:
    sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
env={**os.environ,'RECEIPT_DATA_FILE':str(DATABASE),'RECEIPT_PORT':str(port)}
server=subprocess.Popen([sys.executable,str(ROOT/'app.py')],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
checks=[]
def request(path,body=None,expected=200):
    req=urllib.request.Request(f'http://127.0.0.1:{port}'+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=180) as response:
            assert response.status==expected,(path,response.status)
            return json.loads(response.read())
    except urllib.error.HTTPError as e:
        assert e.code==expected,(path,e.code,e.read())
        return json.loads(e.read())
def wait_job(job):
    for _ in range(160):
        value=request('/api/jobs/'+job)
        if value['state']=='done': return value
        time.sleep(1)
    raise AssertionError('import timed out')
try:
    for _ in range(50):
        try:
            assert request('/api/health').get('local_only') is True
            break
        except Exception: time.sleep(.1)
    data=request('/api/receipts')['receipts']
    assert len(data)==100
    assert all(r.get('benchmark',{}).get('passed') and r.get('ensemble_status')=='complete' for r in data)
    assert all(r.get('merchant') and r.get('date') and r.get('total') is not None for r in data)
    for suffix in ['validation100/evaluation.json','original100/evaluation.json']:
        report=request('/research/evaluations/'+suffix)
        assert report['count']==100
    assert request('/research/evaluations/validation100/evaluation.json')['passed']==100
    checks.append('published 100 core-complete predictions and both review links')
    record=next(r for r in data if r.get('ai_suggestion'))
    before=record['field_evidence']['category']
    result=request('/api/update',{'id':record['id'],'changes':{'notes':'QA temporary note'}})['record']
    assert result['field_evidence']['category']==before
    assert result['edit_history'][-1]['after']=={'notes':'QA temporary note'}
    checks.append('notes-only edit preserves AI category evidence')
    request('/api/update',{'id':record['id'],'changes':{'date':None,'status':'confirmed'}},400)
    request('/api/update',{'id':record['id'],'changes':{'total':float('nan')}},400)
    checks.append('incomplete confirmation and NaN rejected')
    result=request('/api/update',{'id':record['id'],'changes':{'total':0,'status':'review'}})['record']
    assert result['total']==0
    checks.append('zero amount retained')
    ids=[r['id'] for r in data[:3]]
    exported=request('/api/export',{'ids':ids,'format':'json'})
    output=json.loads((ROOT/exported['url'].lstrip('/')).read_text())
    # JSON export is a records array, preserving selected records.
    assert {r['id'] for r in output}==set(ids)
    request('/api/export',{'ids':['not-a-receipt'],'format':'json'},400)
    checks.append('selected export exact ID set and unknown-ID rejection')
    image=ROOT/data[0]['source']['local_path']
    payload={'images':[{'name':image.name,'data':base64.b64encode(image.read_bytes()).decode()}]}
    job=wait_job(request('/api/import',payload,202)['job_id'])
    assert job['duplicates']==1 and job['imported']==0 and len(request('/api/receipts')['receipts'])==100,job
    checks.append('exact duplicate import rejected without increasing count')
    browser_check=subprocess.run([os.environ.get('RECEIPT_NODE',str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node')),str(ROOT/'scripts/check_ui_edit.mjs'),f'http://127.0.0.1:{port}'],capture_output=True,text=True,timeout=90)
    assert browser_check.returncode==0,browser_check.stderr
    checks.append('browser form note-only edit, confirmation and persistence')
    heic=TEST/'real-receipt.heic'
    subprocess.run(['/usr/bin/sips','-s','format','heic',str(ROOT/'data/raw/web/au_web_foi_coles_p25.jpg'),'--out',str(heic)],check=True,capture_output=True)
    job=wait_job(request('/api/import',{'images':[{'name':'real-receipt.heic','data':base64.b64encode(heic.read_bytes()).decode()}]},202)['job_id'])
    assert job['imported']==1 and not job['errors'],job
    imported=request('/api/receipts')['receipts'][-1]
    assert imported['source'].get('preview_path') and (ROOT/imported['source']['preview_path']).is_file()
    assert imported['total']==37.62 and imported['date']=='2025-12-09'
    assert imported['ensemble_status']=='complete',imported.get('warnings')
    assert set(imported['ocr_engines'])=={'paddle','unlimited','oxr'}
    assert all(e['recognition_complete'] for e in imported['ocr_engines'].values())
    checks.append('HEIC import -> all three actual OCR models -> AI -> JPEG preview -> structured fields')
    report=request('/api/report',{'ids':[imported['id']]})
    assert report['summary']['count']==1 and report['record_ids']==[imported['id']]
    assert report['summary']['currencies']['AUD']['total_cents']==3762
    assert report.get('ai_text') and report.get('ai_engine')
    checks.append('selected real local-AI report with computed totals')
    write_json(ROOT/'output/qa/api-check.json',{'passed':True,'checks':checks,'isolation':'copy of real records; main workspace untouched'})
    print(json.dumps({'passed':True,'checks':checks},ensure_ascii=False))
finally:
    server.terminate()
    try: server.wait(timeout=10)
    except subprocess.TimeoutExpired: server.kill()
