"""Loopback-only receipt workflow prototype. Run via start.command."""
import base64
import hashlib
import json
import mimetypes
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from receipt_engine import ROOT, CATEGORIES, build_report, now, read_json, summarize, write_json
from receipt_pipeline import extract_ensemble_record
from exports import create_export, create_report_export
from receipt_workflow import prepare_record, update_record, validate_changes
from local_visual_review import apply_local_visual_review

DATABASE = Path(os.environ.get('RECEIPT_DATA_FILE',str(ROOT/'data/receipts.json'))).resolve()
PROCESSING = DATABASE.with_name('.processing')
LOCK = threading.RLock()
WORKERS = ThreadPoolExecutor(max_workers=1)
JOBS = {}
PORT = int(os.environ.get('RECEIPT_PORT', '8765'))

def records():
    return read_json(DATABASE, [])

def selected(ids):
    if not isinstance(ids, list) or not ids or not all(isinstance(i,str) for i in ids):
        raise ValueError('Select at least one receipt')
    wanted = set(ids)
    data = [r for r in records() if r['id'] in wanted]
    if len(data) != len(wanted): raise ValueError('Some selected receipts no longer exist. Refresh and try again.')
    return data

def import_images(images, job_id):
    job = JOBS[job_id]
    for image in images:
        try:
            raw = base64.b64decode(image['data'], validate=True)
            if len(raw) > 24*1024*1024: raise ValueError('Each image must be smaller than 24 MB')
            digest = hashlib.sha256(raw).hexdigest()
            with LOCK:
                if any(r.get('sha256')==digest for r in records()):
                    job['duplicates'] += 1; continue
            suffix = Path(image.get('name','')).suffix.lower()
            if suffix not in ['.jpg','.jpeg','.png','.webp','.heic','.heif','.tif','.tiff']: raise ValueError('Choose JPG, PNG, WebP, HEIC or TIFF images')
            path = ROOT/'data/uploads'/f'{digest}{suffix}'
            path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(raw)
            from PIL import Image
            try:
                with Image.open(path) as img:
                    if img.width*img.height > 80_000_000: raise ValueError('Image dimensions are too large')
                    img.verify()
            except Exception:
                if suffix not in ['.heic','.heif']: raise
            record = prepare_record(extract_ensemble_record(path, {'kind':'user_import','page_url':'','license':'User supplied','original_name':image.get('name','')}, allow_detail_review=False))
            record = prepare_record(apply_local_visual_review(record))
            with LOCK:
                data = records(); data.append(record); write_json(DATABASE,data)
            job['imported'] += 1
        except Exception as e:
            job['errors'].append({'name':image.get('name',''), 'error':str(e)[:500]})
        finally:
            job['done'] += 1
    job['state'] = 'done'

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def send_json(self, value, code=200):
        raw = json.dumps(value,ensure_ascii=False).encode()
        self.send_response(code); self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(raw)))
        self.end_headers(); self.wfile.write(raw)

    def body(self):
        length = int(self.headers.get('Content-Length','0'))
        if length < 0 or length > 150*1024*1024: raise ValueError('Import up to 150 MB at a time')
        value = json.loads(self.rfile.read(length))
        if not isinstance(value,dict): raise ValueError('The request must be a JSON object')
        return value

    def trusted(self):
        host = self.headers.get('Host','').split(':')[0]
        if host not in ['localhost','127.0.0.1']: return False
        origin = self.headers.get('Origin')
        return not origin or origin in [f'http://localhost:{PORT}', f'http://127.0.0.1:{PORT}']

    def do_GET(self):
        if not self.trusted(): return self.send_json({'error':'Local access only'},403)
        path = unquote(urlparse(self.path).path)
        if path == '/api/receipts':
            with LOCK: data = records()
            return self.send_json({'receipts':data,'summary':summarize(data),'categories':CATEGORIES,'processing':PROCESSING.exists()})
        if path == '/api/health': return self.send_json({'ok':True,'engine':'PaddleOCR + Unlimited OCR (U2) + OXR + evidence reconciliation','classification':'Apple Foundation Models (optional)','local_only':True})
        if path == '/api/blind-status':
            try:
                progress = read_json(ROOT/'research/blind100/watch-status.json', {'state':'not_started','completed':0})
            except (OSError,json.JSONDecodeError):
                progress = {'state':'updating'}
            try:
                evaluation = read_json(ROOT/'research/blind100/evaluation.json', {})
            except (OSError,json.JSONDecodeError):
                evaluation = {}
            if evaluation.get('complete'):
                progress = {**progress,'state':'complete','completed':evaluation['tested_count'],
                            'fields':evaluation['fields'],'automatic':evaluation['automatic'],
                            'timing_seconds':evaluation['timing_seconds'],'report_url':'/output/quality/blind100.html'}
            return self.send_json({'target_count':100,**progress})
        if path.startswith('/api/jobs/'):
            value = JOBS.get(path.split('/')[-1])
            return self.send_json(value if value else {'error':'Job not found'},200 if value else 404)
        if path == '/api/sample-report':
            report = read_json(ROOT/'data/sample_report.json',{})
            with LOCK: snapshot = records()
            current = hashlib.sha256(json.dumps(snapshot,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            if report:
                report['stale'] = (report.get('fingerprint') != current
                                   or bool(report.get('ai_text') and report.get('ai_method') != 'prioritised_verified_actions'))
            return self.send_json(report)
        if path == '/': file = ROOT/'static/index.html'
        elif path in ['/app.js','/workflow.js','/style.css']: file = ROOT/'static'/path[1:]
        elif path == '/output/quality/index.html': file = ROOT/'output/quality/index.html'
        elif path in ['/research/validation100_manifest.json','/research/sample_100_manifest.json',
                      '/research/validation100_reference_changes.json',
                      '/research/evaluations/validation100/evaluation.json','/research/evaluations/validation100/predictions.json',
                      '/research/evaluations/original100/evaluation.json','/research/evaluations/original100/predictions.json']:
            file = ROOT/path[1:]
        elif path.startswith(('/data/raw/','/data/uploads/','/data/previews/','/output/')):
            file = (ROOT/path[1:]).resolve()
            if not file.is_relative_to(ROOT) or file.suffix.lower() not in ['.png','.jpg','.jpeg','.webp','.heic','.heif','.pdf','.xlsx','.csv','.json','.md','.zip','.html']:
                return self.send_json({'error':'Invalid path'},404)
        else: return self.send_json({'error':'Page not found'},404)
        if not file.is_file(): return self.send_json({'error':'File not found'},404)
        self.send_response(200)
        self.send_header('Content-Type',mimetypes.guess_type(str(file))[0] or 'application/octet-stream')
        self.send_header('Content-Length',str(file.stat().st_size))
        self.send_header('X-Content-Type-Options','nosniff')
        if path.startswith('/output/') and file.suffix.lower() != '.html':
            self.send_header('Content-Disposition',f'attachment; filename="{file.name}"')
        self.end_headers(); self.wfile.write(file.read_bytes())

    def do_POST(self):
        if not self.trusted(): return self.send_json({'error':'Only requests from the local workspace are allowed'},403)
        try:
            payload = self.body()
            if self.path in ['/api/update','/api/bulk-update','/api/import'] and PROCESSING.exists():
                return self.send_json({'error':'Batch processing is in progress. Refresh when it finishes.'},409)
            if self.path == '/api/import':
                images = payload.get('images',[])
                if not isinstance(images,list) or not 1 <= len(images) <= 40 or any(not isinstance(i,dict) for i in images): raise ValueError('Choose 1 to 40 images per batch')
                job_id = uuid.uuid4().hex
                JOBS[job_id] = {'state':'running','total':len(images),'done':0,'imported':0,'duplicates':0,'errors':[]}
                WORKERS.submit(import_images,images,job_id)
                return self.send_json({'job_id':job_id},202)
            if self.path == '/api/update':
                updates = validate_changes(payload.get('changes',{}))
                with LOCK:
                    data = records(); index = next((i for i,r in enumerate(data) if r['id']==payload.get('id')),None)
                    if index is None: raise ValueError('Receipt not found')
                    record = update_record(data[index], updates)
                    data[index] = record
                    write_json(DATABASE,data)
                return self.send_json({'record':record})
            if self.path == '/api/bulk-update':
                updates = validate_changes(payload.get('changes',{}), bulk=True)
                with LOCK:
                    wanted = {r['id'] for r in selected(payload.get('ids'))}
                    data = records()
                    updated = [update_record(r, updates) if r['id'] in wanted else r for r in data]
                    changed = [r for r in updated if r['id'] in wanted]
                    write_json(DATABASE,updated)
                return self.send_json({'count':len(changed),'records':changed})
            if self.path == '/api/export':
                with LOCK: data = selected(payload.get('ids'))
                if 'expected_records' in payload:
                    fields = ('id','merchant','date','total','currency','category','purpose','tags','notes','status')
                    expected = payload['expected_records']
                    actual = [{key: r.get(key) for key in fields} for r in data]
                    if not isinstance(expected,list) or any(not isinstance(r,dict) for r in expected):
                        raise ValueError('Invalid export preview')
                    if sorted(expected,key=lambda r:str(r.get('id'))) != sorted(actual,key=lambda r:str(r.get('id'))):
                        return self.send_json({'error':'Receipts changed after preview. Close this preview, refresh, and preview again.'},409)
                fmt = payload.get('format')
                if fmt not in ['xlsx','pdf','csv','json']: raise ValueError('Unsupported export format')
                path = ROOT/'output/exports'/f'receipts-{len(data)}-{uuid.uuid4().hex[:8]}.{fmt}'
                create_export(data,fmt,path)
                return self.send_json({'url':'/'+str(path.relative_to(ROOT)),'count':len(data),'summary':summarize(data)})
            if self.path == '/api/report':
                with LOCK: data = selected(payload.get('ids'))
                report = build_report(data)
                name = 'report-'+uuid.uuid4().hex[:8]
                downloads = {}
                for fmt in ('json','html','pdf'):
                    path = ROOT/'output/reports'/f'{name}.{fmt}'
                    create_report_export(report,fmt,path)
                    downloads[fmt] = '/'+str(path.relative_to(ROOT))
                return self.send_json({**report,'download_url':downloads['json'],'downloads':downloads})
            self.send_json({'error':'Endpoint not found'},404)
        except (ValueError,KeyError,TypeError) as e:
            self.send_json({'error':str(e)},400)
        except Exception as e:
            self.send_json({'error':str(e)[:600]},500)

if __name__ == '__main__':
    print(f'Receipt workspace: http://127.0.0.1:{PORT}',flush=True)
    server = ThreadingHTTPServer(('127.0.0.1',PORT),Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
