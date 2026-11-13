"""Adapters for the user's verified, offline Paddle / U2 / OXR installations."""
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from PIL import Image, ImageOps

ROOT=Path(__file__).resolve().parent
EXISTING=ROOT.parent/'pdf-to-ppt/ocr'
MLX=ROOT.parent/'ocr-mac-test'
PYTHONS={'paddle':EXISTING/'.venv/bin/python','unlimited':MLX/'.venv/bin/python','oxr':MLX/'.venv/bin/python'}
CACHE=ROOT/'data/ensemble'

def environment():
    return {**os.environ,'PYTHONDONTWRITEBYTECODE':'1','HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','HF_HUB_DISABLE_TELEMETRY':'1',
            'SMARTPPT_OCR_MODELS':str(EXISTING/'models'),'SMARTPPT_U2_MODEL':str(MLX/'models/u2'),
            'SMARTPPT_OXR_SOURCE':str(MLX/'upstream/OXR-b2ee4ac12ed220bf7fefa74951babf0d3b05e766'),
            'SMARTPPT_OXR_MODEL':str(MLX/'models/oxr'),'SMARTPPT_OXR_LAYOUT_URL':'http://127.0.0.1:18081'}

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def prepare_images(manifest):
    normalized=CACHE/'normalized'; oriented=CACHE/'oriented'
    normalized.mkdir(parents=True,exist_ok=True); oriented.mkdir(parents=True,exist_ok=True)
    pending=[]; mapping=[]
    for item in manifest:
        original=ROOT/item['local_path']; target=normalized/(item['id']+'.png')
        original_sha=sha(original)
        meta=target.with_suffix('.source.json')
        old=json.loads(meta.read_text()) if meta.exists() else {}
        if not target.exists() or old.get('source_sha256')!=original_sha or old.get('normalized_sha256')!=sha(target):
            normalization_warnings=[]
            with Image.open(original) as image:
                image.load()
                try:
                    prepared=ImageOps.exif_transpose(image).convert('RGB')
                except (SyntaxError,ValueError,OSError) as exc:
                    # Broken metadata must not discard otherwise decodable pixels.
                    # The separate visual orientation model still examines the image.
                    prepared=Image.frombytes('RGB',image.size,image.convert('RGB').tobytes())
                    normalization_warnings.append('invalid_exif_ignored: '+str(exc))
                prepared.info.clear()
                prepared.save(target)
            meta.write_text(json.dumps({'source_path':str(original.relative_to(ROOT)),'source_sha256':original_sha,'normalized_sha256':sha(target),'normalization_warnings':normalization_warnings}))
        output=oriented/target.name
        orientation=output.with_suffix('.orientation.json')
        previous=json.loads(orientation.read_text()) if orientation.exists() else {}
        if not output.exists() or previous.get('input_sha256')!=sha(target) or previous.get('output_sha256')!=sha(output): pending.append(target)
        mapping.append({'id':item['id'],'source_path':item['local_path'],'source_sha256':original_sha,'prepared_path':str(output.relative_to(ROOT))})
    if pending:
        if os.environ.get('SMARTOCR_RESIDENT') == '1':
            from resident_ocr import request
            request('orientation', {'images':list(map(str,pending)), 'out':str(oriented)})
        else:
            subprocess.run([str(PYTHONS['paddle']),str(EXISTING/'orientation_runner.py'),'--out',str(oriented),*map(str,pending)],env=environment(),check=True,cwd=ROOT)
    return mapping

def run_engine(engine,mapping):
    out=CACHE/engine; out.mkdir(parents=True,exist_ok=True)
    pending=[]
    for item in mapping:
        image=ROOT/item['prepared_path']; result=out/(item['id']+'.json')
        cached=json.loads(result.read_text()) if result.exists() else {}
        if cached.get('input_sha256')!=sha(image): pending.append(image)
    run_key=hashlib.sha256('\n'.join(item['id'] for item in mapping).encode()).hexdigest()[:12]
    log_dir=CACHE/'logs'; log_dir.mkdir(parents=True,exist_ok=True)
    log=log_dir/(engine+'-'+run_key+'.log')
    started=time.monotonic()
    if pending:
        command=[str(PYTHONS[engine]),str(EXISTING/(engine+'_runner.py')),'--out',str(out),*map(str,pending)]
        if engine == 'paddle' and os.environ.get('SMARTOCR_RESIDENT') == '1':
            from resident_ocr import request
            metadata = request('paddle', {'images':list(map(str,pending)), 'out':str(out)})
            log.write_text(json.dumps(metadata))
        else:
            with log.open('w') as stream:
                # A capped/repeating decoder must not hold a batch indefinitely.
                # Timeout is an unavailable engine, never successful extraction.
                budget=180*len(pending)
                try:
                    process=subprocess.run(command,cwd=ROOT,env=environment(),stdout=stream,stderr=subprocess.STDOUT,timeout=budget)
                except subprocess.TimeoutExpired as exc:
                    raise RuntimeError(f'{engine} exceeded {budget}s budget; inspect {log.relative_to(ROOT)}') from exc
            if process.returncode: raise RuntimeError(f'{engine} failed ({process.returncode}), inspect {log.relative_to(ROOT)}')
    return {'engine':engine,'requested':len(mapping),'processed':len(pending),'cached':len(mapping)-len(pending),'elapsed_s':round(time.monotonic()-started,2),'log':str(log.relative_to(ROOT))}

def normalized_output(engine,record):
    """Keep both original transcript and geometry; do not rewrite OCR facts."""
    width,height=record.get('image_size',[1,1])
    lines=[]
    if engine=='paddle':
        for line in record.get('lines',[]):
            xs=[p[0] for p in line['polygon']]; ys=[p[1] for p in line['polygon']]
            lines.append({'text':line['text'],'confidence':line.get('confidence'),'x':min(xs)/width,'y':1-max(ys)/height,'width':(max(xs)-min(xs))/width,'height':(max(ys)-min(ys))/height})
        text='\n'.join(l['text'] for l in lines)
    else:
        scale_x,scale_y=(1000,1000) if record.get('coordinate_space')=='normalized-1000' else (width,height)
        for block in record.get('blocks',[]):
            content=block.get('content') or ''
            if not isinstance(content,str): content=json.dumps(content,ensure_ascii=False)
            box=block.get('bbox')
            if not box or len(box)!=4: continue
            x1,y1,x2,y2=box
            lines.append({'text':content,'x':x1/scale_x,'y':1-y2/scale_y,'width':(x2-x1)/scale_x,'height':(y2-y1)/scale_y})
        text='\n'.join(l['text'] for l in lines)
        if not text: text=record.get('raw','')
    return {'engine':record.get('engine',engine),'text':text,'lines':lines,'capped':record.get('capped',False),'seconds':record.get('seconds'),'input_sha256':record.get('input_sha256')}


def run_focused_oxr(mapping):
    """Try focus, readable focus, then direct OXR recognition of the same view.

    All presentations remain the single OXR focus variant consumed by the
    pipeline. Previous JSON bytes are archived before metadata or output changes.
    A matching direct result is reused even if still incomplete: repeated calls
    must not run an identical unsuccessful image indefinitely.
    """
    from focused_ocr import prepare_focus
    from ocr_view_retry import prepare_readable_focus
    out=CACHE/'oxr_focus';out.mkdir(parents=True,exist_ok=True)
    started=time.monotonic();pending=[];metadata={};inputs={};enlarged={};logs=[]

    def read(path):
        return json.loads(path.read_text()) if path.exists() else {}

    def incomplete(raw):
        useful=any(any(char.isalnum() for char in str(block.get('content') or ''))
                   and str(block.get('label','')).lower() not in ('image','picture','figure')
                   for block in raw.get('blocks',[]))
        return bool(raw.get('error') or raw.get('capped') or not useful)

    def direct_attempted(raw):
        return str(raw.get('recognition_variant','')).startswith('direct_') and raw.get('layout_bypassed') is True

    def archive(path):
        if not path.exists():return
        directory=CACHE/'oxr_focus_attempts'/path.stem;directory.mkdir(parents=True,exist_ok=True)
        history=directory/(sha(path)+'.json')
        if not history.exists():history.write_bytes(path.read_bytes())

    def attach(rid):
        path=out/f'{rid}.json';raw=read(path);meta=metadata[rid]
        if raw.get('input_sha256')!=meta['output_sha256']:return False
        updated={**raw,'variant':'focus','source_input_sha256':meta['source_sha256'],'focus':meta,
                 'preprocessing_variant':'readable_focus' if meta.get('variant')=='readable_focus_retry' else 'original_focus'}
        if updated!=raw:
            archive(path)
            temporary=path.with_suffix('.json.tmp');temporary.write_text(json.dumps(updated,ensure_ascii=False,indent=2));temporary.replace(path)
        return True

    def readable(rid):
        if rid not in enlarged:
            image,paddle=inputs[rid]
            enlarged[rid]=prepare_readable_focus(image,paddle,CACHE/'focus_enlarged'/f'{rid}.png')
        return enlarged[rid]

    def run(views,stage):
        if not views:return
        log=out/f'run-{time.time_ns()}-{stage}.log';logs.append(log)
        for view in views:archive(out/(view.stem+'.json'))
        if stage=='direct-text':
            command=[str(PYTHONS['oxr']),str(ROOT/'scripts/run_direct_oxr.py'),'--out',str(out),
                     '--task','text','--repetition-penalty','1.05','--images',*map(str,views)]
        else:
            command=[str(PYTHONS['oxr']),str(EXISTING/'oxr_runner.py'),'--out',str(out),*map(str,views)]
        with log.open('w') as stream:
            result=subprocess.run(command,cwd=ROOT,env=environment(),stdout=stream,stderr=subprocess.STDOUT)
        # Attach successful earlier results even if a later image crashed.
        attached={view.stem:attach(view.stem) for view in views}
        if stage=='direct-text':
            for rid in attached:
                raw=read(out/f'{rid}.json')
                attached[rid]=attached[rid] and raw.get('recognition_variant')=='direct_text' and direct_attempted(raw) and bool(raw.get('calls'))
        if result.returncode:raise RuntimeError(f'OXR {stage} retry failed; inspect {log}')
        missing=[rid for rid,valid in attached.items() if not valid]
        if missing:raise RuntimeError(f'OXR {stage} returned missing or mismatched output for {missing}; inspect {log}')

    for item in mapping:
        image=ROOT/item['prepared_path'];rid=item['id']
        paddle=json.loads((CACHE/'paddle'/f'{rid}.json').read_text())
        inputs[rid]=(image,paddle)
        view=CACHE/'focus'/f'{rid}.png'
        meta=prepare_focus(image,paddle,view);metadata[rid]=meta
        cached=read(out/f'{rid}.json')
        if cached.get('input_sha256')!=meta['output_sha256']:
            # A prior readable retry may also have crashed before attaching its
            # metadata. Recompute deterministic pixels to verify it, not labels.
            if cached.get('input_sha256') and cached['input_sha256']==readable(rid)['output_sha256']:
                metadata[rid]=enlarged[rid]
            else:
                pending.append(view);continue
        attach(rid)  # Includes valid raw caches that need no GPU inference.
    run(pending,'focus')
    retry=[]
    for item in mapping:
        rid=item['id'];raw=read(out/f'{rid}.json')
        if incomplete(raw) and metadata[rid].get('variant')!='readable_focus_retry':
            metadata[rid]=readable(rid)
            retry.append(Path(metadata[rid]['output_path']))
    run(retry,'readable-focus')
    direct=[]
    for item in mapping:
        rid=item['id'];raw=read(out/f'{rid}.json')
        if incomplete(raw) and not direct_attempted(raw):
            direct.append(Path(metadata[rid]['output_path']))
    run(direct,'direct-text')
    exhausted=sum(incomplete(read(out/f"{item['id']}.json")) for item in mapping)
    return {'engine':'oxr','variant':'focus','requested':len(mapping),
            'processed':len(pending)+len(retry)+len(direct),'focus_processed':len(pending),
            'readable_processed':len(retry),'direct_processed':len(direct),'retry_exhausted':exhausted,
            'status':'incomplete' if exhausted else 'complete',
            'elapsed_s':round(time.monotonic()-started,2),
            'log':str(logs[-1].relative_to(ROOT)) if logs else None,
            'logs':[str(log.relative_to(ROOT)) for log in logs]}


def run_detail_review(mapping):
    """Run disagreement-triggered reviews using an image-only temporary manifest."""
    jobs=CACHE/'jobs';jobs.mkdir(parents=True,exist_ok=True)
    key=hashlib.sha256('\n'.join(item['id'] for item in mapping).encode()).hexdigest()[:16]
    manifest=jobs/f'detail-{key}.json'
    manifest.write_text(json.dumps([{'id':item['id'],'local_path':item['source_path']} for item in mapping],indent=2))
    log=jobs/f'detail-{key}-{time.time_ns()}.log';started=time.monotonic()
    with log.open('w') as stream:
        result=subprocess.run([os.environ.get('RECEIPT_PYTHON',str((Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3'))),str(ROOT/'scripts/run_detail_reviews.py'),'--manifest',str(manifest)],cwd=ROOT,env=environment(),stdout=stream,stderr=subprocess.STDOUT)
    if result.returncode:raise RuntimeError(f'Detail review failed; inspect {log}')
    return {'stage':'detail_review','requested':len(mapping),'elapsed_s':round(time.monotonic()-started,2),'log':str(log.relative_to(ROOT))}


def run_focused_unlimited(mapping):
    """Use the same focus-first U2 runner as batch acceptance, including fallback.

    The job manifest contains only image IDs and paths. All field annotations,
    source hints and reference answers are deliberately excluded. Paddle and
    prepared-image hashes must match before the model runner is started.
    """
    import re
    import tempfile

    manifest=[]
    for item in mapping:
        record_id=item.get('id')
        if not isinstance(record_id,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,120}',record_id):
            raise ValueError('Invalid receipt ID for focused U2 job')
        prepared=(ROOT/item['prepared_path']).resolve()
        expected=(CACHE/'oriented'/f'{record_id}.png').resolve()
        if prepared!=expected or not prepared.is_file():
            raise RuntimeError(f'{record_id}: prepared image missing for focused U2')
        paddle_path=CACHE/'paddle'/f'{record_id}.json'
        paddle=json.loads(paddle_path.read_text()) if paddle_path.is_file() else {}
        if paddle.get('input_sha256')!=sha(prepared) or paddle.get('error'):
            raise RuntimeError(f'{record_id}: matching Paddle evidence is required before focused U2')
        source_path=Path(item.get('source_path') or item.get('local_path') or item['prepared_path'])
        source=(ROOT/source_path).resolve()
        try:
            local_path=str(source.relative_to(ROOT))
        except ValueError as exc:
            raise ValueError('Focused U2 source must belong to the receipt workspace') from exc
        if not source.is_file():
            raise RuntimeError(f'{record_id}: source image missing for focused U2')
        manifest.append({'id':record_id,'local_path':local_path})
    if not manifest:
        return {'engine':'unlimited','strategy':'focus_then_full_fallback','requested':0,'elapsed_s':0.0}
    jobs=CACHE/'jobs'; jobs.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',prefix='u2-focus-',suffix='.json',dir=jobs,delete=False) as handle:
        json.dump(manifest,handle,ensure_ascii=False,indent=2)
        manifest_path=Path(handle.name)
    log_dir=CACHE/'logs'; log_dir.mkdir(parents=True,exist_ok=True)
    log=log_dir/(manifest_path.stem+'.log')
    command=[str(PYTHONS['unlimited']),str(ROOT/'scripts/run_focused_unlimited.py'),
             '--manifest',str(manifest_path.relative_to(ROOT))]
    started=time.monotonic()
    if os.environ.get('SMARTOCR_RESIDENT') == '1':
        from resident_ocr import request
        metadata = request('unlimited', {'manifest':str(manifest_path)}, timeout=240)
        log.write_text(json.dumps(metadata))
    else:
        with log.open('w') as stream:
            process=subprocess.run(command,cwd=ROOT,env=environment(),stdout=stream,stderr=subprocess.STDOUT)
        if process.returncode:
            raise RuntimeError(f'Focused U2 failed ({process.returncode}), inspect {log.relative_to(ROOT)}')
    return {'engine':'unlimited','strategy':'focus_then_full_fallback','requested':len(manifest),
            'elapsed_s':round(time.monotonic()-started,2),
            'manifest':str(manifest_path.relative_to(ROOT)),'log':str(log.relative_to(ROOT))}
