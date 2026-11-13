"""Process approved photos; reference annotations never enter the OCR/AI prompt."""
import argparse
import copy
import concurrent.futures
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from receipt_engine import *

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--skip-ai',action='store_true')
    parser.add_argument('--limit',type=int,default=100)
    args = parser.parse_args()
    manifest = read_json(ROOT/'research/sample_100_manifest.json',[])[:args.limit]
    if not manifest: raise RuntimeError('Approved sample manifest missing')
    cache = ROOT/'data/ocr_cache'; cache.mkdir(parents=True,exist_ok=True)
    def process(item):
        path = ROOT/item['local_path']
        cache_file = cache/(item['id']+'.json')
        ocr = read_json(cache_file)
        if ocr is None:
            ocr = ocr_image(path); write_json(cache_file,ocr)
        source = {k:item.get(k) for k in ['image_url','license','merchant_hint','currency_hint','kind','attribution','source_family','quality_flags'] if item.get(k) is not None}
        source['page_url'] = item.get('source_page_url') or item.get('source_url')
        return extract_record(path,source,ocr,item['id'])
    results = []
    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        future_items = {pool.submit(process,item):item for item in manifest}
        for future in concurrent.futures.as_completed(future_items):
            item = future_items[future]
            try: results.append(future.result())
            except Exception as e: print(json.dumps({'failed':item['id'],'error':str(e)}),flush=True)
            print(f'OCR {len(results)}/{len(manifest)}',flush=True)
    index = {item['id']:i for i,item in enumerate(manifest)}
    results.sort(key=lambda r:index[r['id']])
    write_json(ROOT/'data/receipts.json',results)
    write_json(ROOT/'data/baseline_extraction.json',results)
    if not args.skip_ai:
        ai_cache = ROOT/'data/ai_cache'; ai_cache.mkdir(exist_ok=True)
        def enrich(record):
            record = copy.deepcopy(record)
            path = ai_cache/(record['id']+'.json')
            cached = read_json(path)
            if cached and cached.get('ocr_text')==record['ocr_text'] and cached.get('ai_suggestion'):
                return enrich_with_ai(record,cached['ai_suggestion'])
            record = enrich_with_ai(record); write_json(path,record); return record
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = {pool.submit(enrich,record):i for i,record in enumerate(results)}
            completed=0
            for future in concurrent.futures.as_completed(futures):
                i = futures[future]; results[i] = future.result(); completed+=1
                write_json(ROOT/'data/receipts.json',results)
                print(f'AI {completed}/{len(results)} {results[i]["id"]} '+('OK' if results[i].get('ai_suggestion') else str(results[i].get('ai_error'))[:120]),flush=True)
    report = build_report(results,use_ai=not args.skip_ai)
    write_json(ROOT/'data/sample_report.json',report)
    write_json(ROOT/'research/run_metrics.json',{'count':len(results),'elapsed_s':round(time.monotonic()-started,2),'ocr_ms':[r['ocr_ms'] for r in results],'ai_success':sum(bool(r.get('ai_suggestion')) for r in results),'summary':summarize(results)})
    print(json.dumps({'finished':len(results),'summary':summarize(results)},ensure_ascii=False),flush=True)

if __name__=='__main__': main()
