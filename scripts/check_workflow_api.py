"""Exercise the real HTTP workflow on a temporary copy; never start OCR.

The sole import request uses bytes whose SHA-256 is already in the copied DB.
One /api/report request invokes the real local language model (no mock).
"""
import base64
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from receipt_engine import amount_cents, now, write_json


def run():
    source=ROOT/'data/receipts.json'
    source_bytes=source.read_bytes()
    source_sha=hashlib.sha256(source_bytes).hexdigest()
    output=ROOT/'output/qa/workflow-api'
    output.mkdir(parents=True,exist_ok=True)
    result={'passed':False,'started_at':now(),'checks':[],'main_database_sha256_before':source_sha,
            'ocr_invocations':0,'real_ai_report_requests':0,'isolation':'Temporary database copy and random loopback port; original receipts are never updated.'}
    server=None
    def check(name,**details):result['checks'].append({'check':name,'passed':True,**details})
    try:
        with tempfile.TemporaryDirectory(prefix='receipt-workflow-http-') as directory:
            database=Path(directory)/'receipts.json'
            database.write_bytes(source_bytes)
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            result['port']=port
            env={**os.environ,'RECEIPT_DATA_FILE':str(database),'RECEIPT_PORT':str(port)}
            with (output/'server.log').open('w') as log:
                server=subprocess.Popen([sys.executable,str(ROOT/'app.py')],cwd=ROOT,env=env,stdout=log,stderr=log)
            base=f'http://127.0.0.1:{port}'

            def request(path,body=None,expected=200,raw=False,headers=None):
                req=urllib.request.Request(base+path,data=None if body is None else json.dumps(body).encode(),
                                           headers={'Content-Type':'application/json',**(headers or {})})
                try:
                    with urllib.request.urlopen(req,timeout=150) as response:
                        assert response.status==expected,(path,response.status,expected)
                        payload=response.read()
                        return payload if raw else json.loads(payload)
                except urllib.error.HTTPError as error:
                    payload=error.read()
                    assert error.code==expected,(path,error.code,expected,payload.decode(errors='replace'))
                    return payload if raw else json.loads(payload)

            for _ in range(100):
                if server.poll() is not None:raise AssertionError('Server exited: '+(output/'server.log').read_text())
                try:
                    assert request('/api/health')['local_only'] is True
                    break
                except urllib.error.URLError:time.sleep(.1)
            else:raise AssertionError('Server did not start')
            initial=request('/api/receipts')
            data=initial['receipts'];summary=initial['summary']
            assert summary['count']==len(data)
            assert summary['auto_confirmed']==sum(r['status']=='auto_confirmed' for r in data)
            assert summary['review_count']==sum(r['status']=='review' for r in data)
            assert summary['human_confirmed']==sum(r['status']=='confirmed' for r in data)
            assert len(initial['categories'])==9 and all(not any('\u3400'<=ch<='\u9fff' for ch in value) for value in initial['categories'])
            assert all(record['merchant'] and record['date'] and record['total'] is not None for record in data)
            check('Initial English workflow counts match saved user records',count=len(data),auto_confirmed=summary['auto_confirmed'],needs_review=summary['review_count'])

            automatic=[record for record in data if record['status']=='auto_confirmed']
            first,second=automatic[:2]
            original=first['original_extraction']
            core={key:first.get(key) for key in ('merchant','date','total','currency')}
            first_id=first['id'];second_id=second['id']
            note=request('/api/update',{'id':first_id,'changes':{'notes':'Isolated API test note'}})['record']
            assert note['status']=='auto_confirmed' and note['original_extraction']==original
            assert note['field_evidence']['category']==first['field_evidence']['category']
            assert {key:note.get(key) for key in core}==core
            category=request('/api/update',{'id':first_id,'changes':{'category':'Other'}})['record']
            assert category['status']=='auto_confirmed' and category['original_extraction']==original
            assert {key:category.get(key) for key in core}==core
            check('Notes and category edits preserve automatic confirmation and core extraction')

            corrected_total=round(float(core['total'])+0.01,2)
            corrected=request('/api/update',{'id':first_id,'changes':{'total':corrected_total}})['record']
            assert corrected['status']=='confirmed' and corrected['review_decision']['mode']=='override'
            assert corrected['original_extraction']==original
            assert corrected['edit_history'][-1]['before']['total']==core['total']
            assert corrected['edit_history'][-1]['after']['total']==corrected_total
            assert corrected['edit_history'][-1]['before']['status']=='auto_confirmed'
            assert corrected['edit_history'][-1]['after']['status']=='confirmed'
            check('Core override creates human confirmation and preserves original values and history')
            reopened=request('/api/update',{'id':first_id,'changes':{'status':'review'}})['record']
            assert reopened['status']=='review' and reopened['review_decision']['mode']=='manual_reopen'
            still_reopened=request('/api/update',{'id':first_id,'changes':{'notes':'Keep the manual review decision'}})['record']
            assert still_reopened['status']=='review'
            human=request('/api/update',{'id':first_id,'changes':{'status':'confirmed'}})['record']
            assert human['status']=='confirmed' and human['review_decision']['mode']=='human_confirmed'
            check('Manual reopen persists through metadata edits and can be explicitly confirmed')

            scope=[first_id,second_id]
            before_bulk={record['id']:record for record in request('/api/receipts')['receipts'] if record['id'] in scope}
            bulk=request('/api/bulk-update',{'ids':scope,'changes':{'category':'Dining','purpose':'personal','tags':['API test','API test',' selected ']}})
            assert bulk['count']==2
            for record in bulk['records']:
                assert record['category']=='Dining' and record['purpose']=='personal' and set(['API test','selected']).issubset(record['tags']) and len(record['tags'])==len(set(record['tags']))
                assert record['status']==before_bulk[record['id']]['status']
                assert record['original_extraction']==before_bulk[record['id']]['original_extraction']
                assert all(record.get(key)==before_bulk[record['id']].get(key) for key in core)
            check('Bulk category, purpose and tags update only the selected records and preserve core fields')

            cleared=request('/api/update',{'id':first_id,'changes':{'date':None}})['record']
            assert cleared['date'] is None and cleared['status']=='review'
            restored=request('/api/update',{'id':first_id,'changes':{'date':core['date']}})['record']
            assert restored['status']=='confirmed'
            check('Clearing a date returns to review without losing the original extraction')

            invalid=[
                ('/api/bulk-update',{'ids':[first_id,'NOT-A-RECEIPT'],'changes':{'category':'Other'}}),
                ('/api/bulk-update',{'ids':scope,'changes':{'total':0}}),
                ('/api/bulk-update',{'ids':scope,'changes':{'status':'confirmed'}}),
                ('/api/update',{'id':first_id,'changes':{'total':float('nan')}}),
                ('/api/update',{'id':first_id,'changes':{'total':True}}),
                ('/api/update',{'id':first_id,'changes':{'total':'12.34'}}),
                ('/api/update',{'id':first_id,'changes':{'date':'2026-02-31'}}),
                ('/api/update',{'id':first_id,'changes':{'merchant':'','status':'confirmed'}}),
                ('/api/update',{'id':first_id,'changes':{'category':'Not a category'}}),
                ('/api/update',{'id':first_id,'changes':{'purpose':'deductible'}}),
                ('/api/update',{'id':first_id,'changes':{'status':'auto_confirmed'}}),
                ('/api/update',{'id':first_id,'changes':{'sha256':'tampered'}}),
                ('/api/update',{'id':first_id,'changes':{'tags':['x'*41]}}),
                ('/api/update',{'id':'NOT-A-RECEIPT','changes':{'notes':'invalid'}}),
                ('/api/update',{'id':first_id,'changes':{}}),
                ('/api/update',[]),
                ('/api/export',{'ids':scope,'format':'exe'}),
                ('/api/export',{'ids':[first_id,'NOT-A-RECEIPT'],'format':'json'}),
                ('/api/export',{'ids':[],'format':'json'}),
                ('/api/report',{'ids':['NOT-A-RECEIPT']}),
                ('/api/import',{'images':[]}),
            ]
            for endpoint,payload in invalid:
                before=database.read_bytes()
                assert request(endpoint,payload,400).get('error')
                assert database.read_bytes()==before,(endpoint,'failed request mutated the database')
            request('/api/health',expected=403,headers={'Origin':'https://example.invalid'})
            request('/api/jobs/not-a-job',expected=404)
            check('Invalid changes, restricted bulk fields and unknown IDs are rejected atomically',rejected_requests=len(invalid))

            current=request('/api/receipts')['receipts']
            chosen=[record for record in current if record['id'] in scope]
            expected_ids=[record['id'] for record in chosen]
            excluded=next(record['id'] for record in current if record['id'] not in scope)
            export_results={}
            for fmt in ('json','csv','xlsx','pdf'):
                exported=request('/api/export',{'ids':list(reversed(scope)),'format':fmt})
                assert exported['count']==2 and exported['summary']['count']==2
                content=request(exported['url'],raw=True)
                path=output/('selected.'+fmt);path.write_bytes(content)
                if fmt=='json':
                    parsed=json.loads(content)
                    assert parsed['summary']['count']==2
                    assert [r['id'] for r in parsed['receipts']]==expected_ids
                    assert [r['total'] for r in parsed['receipts']]==[r['total'] for r in chosen]
                    assert all('ocr_text' not in r and 'source' not in r for r in parsed['receipts'])
                elif fmt=='csv':
                    rows=list(csv.DictReader(io.StringIO(content.decode('utf-8-sig'))))
                    assert [row['Receipt ID'] for row in rows]==expected_ids
                    assert [float(row['Amount']) for row in rows]==[float(record['total']) for record in chosen]
                    assert {row['Status'] for row in rows}=={'Auto-confirmed','Human confirmed'}
                    assert all(row['Category']=='Dining' for row in rows)
                elif fmt=='xlsx':
                    from openpyxl import load_workbook
                    book=load_workbook(path,data_only=True)
                    sheet=book['Receipts']
                    assert sheet.max_row==3 and [sheet.cell(row,1).value for row in (2,3)]==expected_ids
                    assert [sheet.cell(row,6).value for row in (2,3)]==[record['total'] for record in chosen]
                    assert book['Overview']['C4'].value==2 and book['Overview']['F4'].value==1 and book['Overview']['F5'].value==1
                else:
                    from pypdf import PdfReader
                    pdf_text='\n'.join(page.extract_text() for page in PdfReader(path).pages)
                    assert all(rid in pdf_text for rid in expected_ids) and excluded not in pdf_text
                    assert 'Auto-confirmed' in pdf_text and 'Human confirmed' in pdf_text
                export_results[fmt]={'bytes':len(content),'url':exported['url'],'sha256':hashlib.sha256(content).hexdigest()}
            result['exports']=export_results
            check('All four downloadable formats contain exactly the selected IDs and preserve typed amounts',ids=expected_ids)

            duplicate=next(record for record in current if record.get('sha256') and record.get('source',{}).get('local_path') and (ROOT/record['source']['local_path']).is_file())
            image_path=ROOT/duplicate['source']['local_path'];image_bytes=image_path.read_bytes()
            assert hashlib.sha256(image_bytes).hexdigest()==duplicate['sha256'],'Import would not be an exact duplicate; refusing to risk OCR'
            before=database.read_bytes()
            job_id=request('/api/import',{'images':[{'name':image_path.name,'data':base64.b64encode(image_bytes).decode()}]},202)['job_id']
            for _ in range(100):
                job=request('/api/jobs/'+job_id)
                if job['state']=='done':break
                time.sleep(.1)
            assert job['state']=='done' and job['duplicates']==1 and job['imported']==0 and not job['errors'],job
            assert database.read_bytes()==before
            check('Exact duplicate import finishes without OCR or database changes',receipt_id=duplicate['id'])

            result['real_ai_report_requests']=1
            started=time.monotonic()
            report=request('/api/report',{'ids':scope})
            result['report_elapsed_seconds']=round(time.monotonic()-started,3)
            assert report['record_ids']==expected_ids and report['summary']['count']==2
            assert report['summary']['missing_total']==report['summary']['missing_date']==report['summary']['missing_merchant']==0
            assert report['summary']['ready_count']==2 and report['summary']['review_count']==0
            expected_cents={}
            for record in chosen:expected_cents[record['currency']]=expected_cents.get(record['currency'],0)+amount_cents(record['total'])
            assert {currency:value['total_cents'] for currency,value in report['summary']['currencies'].items()}==expected_cents
            assert report['ai_status'] in ('ready','unavailable') and report['facts'] and report['narrative'] and report['category_breakdown']
            assert set(report['downloads'])=={'json','html','pdf'} and report['download_url']==report['downloads']['json']
            downloads={}
            for fmt,url in report['downloads'].items():
                content=request(url,raw=True);path=output/('selected-report.'+fmt);path.write_bytes(content)
                if fmt=='json':
                    saved=json.loads(content)
                    assert saved['record_ids']==expected_ids and saved['fingerprint']==report['fingerprint']
                    assert saved['summary']==report['summary']
                else:
                    text=content.decode() if fmt=='html' else '\n'.join(page.extract_text() for page in PdfReader(path).pages)
                    assert all(rid in text for rid in expected_ids) and excluded not in text
                    assert 'Receipt insights' in text
                downloads[fmt]={'url':url,'bytes':len(content)}
            result['report']={'record_ids':report['record_ids'],'ai_status':report['ai_status'],'ai_engine':report.get('ai_engine'),
                              'ai_attempts':report.get('ai_attempts'), 'ai_unavailable_reason':report.get('ai_unavailable_reason'),'downloads':downloads}
            check('Real AI report request and JSON, HTML, PDF downloads remain bound to the same selection',ai_status=report['ai_status'])
            assert report['ai_status']=='ready','The real AI service did not produce usable commentary; deterministic report remains available'
            assert report['ai_text'] and report['ai_engine']
            result['passed']=True
    except Exception as error:
        result['error']=str(error)
        result['traceback']=traceback.format_exc()
    finally:
        if server is not None:
            server.terminate()
            try:server.wait(timeout=10)
            except subprocess.TimeoutExpired:server.kill();server.wait()
        result['main_database_sha256_after']=hashlib.sha256(source.read_bytes()).hexdigest()
        result['main_database_unchanged']=result['main_database_sha256_after']==source_sha
        if not result['main_database_unchanged']:result['passed']=False;result['error']='Main database changed during the isolated test'
        result['finished_at']=now()
        write_json(ROOT/'output/qa/workflow-api-check.json',result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(run())
