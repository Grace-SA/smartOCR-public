"""Re-read model disagreements from source pixels; no answer file is opened."""
import argparse
import concurrent.futures
import json
import subprocess
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ocr_ensemble import ROOT,CACHE,PYTHONS,EXISTING,environment,sha,normalized_output
from receipt_pipeline import extract_ensemble_record,_evidence_content
from receipt_detail_views import prepare_detail


def prepare_requests(manifest,ids=None,fields=None):
    requests=[]; skipped=[]
    for item in manifest:
        rid=item['id']
        if ids and rid not in ids:continue
        try:
            record=extract_ensemble_record(ROOT/item['local_path'],record_id=rid,run_models=False)
        except Exception as error:
            skipped.append({'id':rid,'reason':str(error)});continue
        base=record.get('base_reconciliation') or record['reconciliation']
        targets=[field for field,decision in base['fields'].items()
                 if field in ('merchant','date','total') and (decision.get('disagreement') or decision.get('value') is None)]
        if fields:targets=[field for field in targets if field in fields]
        for field in targets:
            image=CACHE/'oriented'/f'{rid}.png'
            paddle=json.loads((CACHE/'paddle'/f'{rid}.json').read_text())
            target=CACHE/'detail'/field/'images'/f'{rid}.png'
            metadata=prepare_detail(image,paddle,field,target)
            requests.append({'id':rid,'field':field,'path':str(target),'sha256':metadata['output_sha256'],
                             'trigger':'model_disagreement' if base['fields'][field].get('disagreement') else 'missing_field'})
    (CACHE/'detail').mkdir(parents=True,exist_ok=True)
    (CACHE/'detail'/'latest-request.json').write_text(json.dumps({'requests':requests,'skipped':skipped},ensure_ascii=False,indent=2))
    return requests,skipped


def _run_oxr_detail_field(field,selected,out):
    """Bounded layout→direct retry for one field, retaining a single OXR vote."""
    from scripts.run_direct_oxr import input_provenance
    metadata={};logs=[];pending=[]

    def read(rid):
        target=out/(rid+'.json')
        return json.loads(target.read_text()) if target.exists() else {}

    def archive(rid):
        target=out/(rid+'.json')
        if target.exists():
            history=out/'attempts'/rid/(sha(target)+'.json');history.parent.mkdir(parents=True,exist_ok=True)
            if not history.exists():history.write_bytes(target.read_bytes())

    def incomplete(raw):
        text,_=_evidence_content('oxr',raw,normalized_output('oxr',raw)) if raw else ('',[])
        return bool(raw.get('error') or raw.get('capped') or not any(char.isalnum() for char in text))

    def direct_attempted(raw):
        return str(raw.get('recognition_variant','')).startswith('direct_') and raw.get('layout_bypassed') is True

    def attach(rid):
        raw=read(rid);provenance=metadata[rid]
        if raw.get('input_sha256')!=provenance['input_sha256']:return False
        updated={**raw,**provenance}
        if updated!=raw:
            archive(rid)
            target=out/(rid+'.json');temporary=target.with_suffix('.json.tmp')
            temporary.write_text(json.dumps(updated,ensure_ascii=False,indent=2));temporary.replace(target)
        return True

    def run(batch,direct=False):
        if not batch:return
        # Financial rows benefit from the pinned table prompt's row/column
        # structure; merchant/date views remain ordinary text recognition.
        task='table' if field=='total' else 'text'
        stage='direct-'+task if direct else 'layout'
        if direct:
            command=[str(PYTHONS['oxr']),str(ROOT/'scripts/run_direct_oxr.py'),'--out',str(out),
                     '--task',task,'--repetition-penalty','1.05','--images',*[request['path'] for request in batch]]
        else:
            command=[str(PYTHONS['oxr']),str(EXISTING/'oxr_runner.py'),'--out',str(out),*[request['path'] for request in batch]]
        for request in batch:archive(request['id'])
        log=out/f'run-{time.time_ns()}-{stage}.log';logs.append(log)
        with log.open('w') as stream:
            result=subprocess.run(command,cwd=ROOT,env=environment(),stdout=stream,stderr=subprocess.STDOUT)
        valid={request['id']:attach(request['id']) for request in batch}
        if direct:
            for rid in valid:
                raw=read(rid)
                valid[rid]=valid[rid] and raw.get('recognition_variant')=='direct_'+task and direct_attempted(raw) and bool(raw.get('calls'))
        if result.returncode:raise RuntimeError(f'Detail OXR {stage} failed; inspect {log}')
        missing=[rid for rid,success in valid.items() if not success]
        if missing:raise RuntimeError(f'Detail OXR {stage} returned missing or mismatched output for {missing}; inspect {log}')

    for request in selected:
        rid=request['id'];provenance=input_provenance(request['path'])
        if provenance['input_sha256']!=request['sha256'] or provenance['variant']!='detail' or provenance.get('field')!=field:
            raise ValueError('OXR detail request does not match verified field/image provenance')
        metadata[rid]=provenance
        if not attach(rid):pending.append(request)
    run(pending)
    direct=[request for request in selected if incomplete(read(request['id'])) and not direct_attempted(read(request['id']))]
    run(direct,True)
    exhausted=sum(incomplete(read(request['id'])) for request in selected)
    info={'engine':'oxr','field':field,'processed':len(pending)+len(direct),
          'layout_processed':len(pending),'direct_processed':len(direct),
          'retry_exhausted':exhausted,'output_complete':not exhausted,
          'status':'incomplete' if exhausted else 'complete','returncode':0,
          'log':str(logs[-1].relative_to(ROOT)) if logs else None,
          'logs':[str(log.relative_to(ROOT)) for log in logs]}
    print(json.dumps(info),flush=True)
    return info


def run_engine_details(engine,requests):
    completed=[]
    for field in ('merchant','date','total'):
        selected=[request for request in requests if request['field']==field]
        out=CACHE/'detail'/field/engine;out.mkdir(parents=True,exist_ok=True)
        if engine=='oxr':
            if selected:completed.append(_run_oxr_detail_field(field,selected,out))
            continue
        pending=[]
        for request in selected:
            target=out/(request['id']+'.json')
            cached=json.loads(target.read_text()) if target.exists() else {}
            text,_=_evidence_content(engine,cached,normalized_output(engine,cached)) if cached else ('',[])
            if cached.get('input_sha256')!=request['sha256'] or cached.get('capped') or not text.strip():
                pending.append(request)
        if not pending:continue
        if engine=='unlimited':
            command=[str(PYTHONS[engine]),str(ROOT/'scripts/run_focused_unlimited.py'),'--out',str(out),'--images',*[request['path'] for request in pending]]
        else:
            command=[str(PYTHONS[engine]),str(EXISTING/(engine+'_runner.py')),'--out',str(out),*[request['path'] for request in pending]]
        log=out/f'run-{time.time_ns()}.log'
        with log.open('w') as stream:
            result=subprocess.run(command,cwd=ROOT,env=environment(),stdout=stream,stderr=subprocess.STDOUT)
        info={'engine':engine,'field':field,'processed':len(pending),'returncode':result.returncode,'log':str(log.relative_to(ROOT))}
        completed.append(info);print(json.dumps(info),flush=True)
        if result.returncode:raise RuntimeError(f'Detail OCR failed; inspect {log}')
    return completed


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--manifest',default='research/validation100_manifest.json')
    parser.add_argument('--ids',nargs='*');parser.add_argument('--fields',nargs='*',choices=['merchant','date','total'])
    parser.add_argument('--engines',nargs='+',choices=['paddle','unlimited','oxr'],default=['paddle','unlimited','oxr'])
    parser.add_argument('--prepare-only',action='store_true')
    args=parser.parse_args();manifest=json.loads((ROOT/args.manifest).read_text())
    requests,skipped=prepare_requests(manifest,args.ids,args.fields)
    print(json.dumps({'detail_views':len(requests),'records':len({r['id'] for r in requests}),'pending_primary_records':len(skipped)}),flush=True)
    if requests and not args.prepare_only:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(args.engines)) as pool:
            jobs=[pool.submit(run_engine_details,engine,requests) for engine in args.engines]
            for job in concurrent.futures.as_completed(jobs):job.result()
