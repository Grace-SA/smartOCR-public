"""One bounded, offline visual review job. The parent owns the timeout."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.benchmark_visual_receipts import PROMPT,parse_response


def main():
    p=argparse.ArgumentParser();p.add_argument('--request',type=Path,required=True)
    args=p.parse_args();job=json.loads(args.request.read_text());started=time.monotonic()
    if hashlib.sha256(Path(job['prepared_path']).read_bytes()).hexdigest()!=job['recipe']['prepared_sha256']:
        raise ValueError('Prepared image changed before visual inference')
    import mlx.core as mx
    from mlx_vlm import load,generate,apply_chat_template
    model,processor=load(job['model_path'],trust_remote_code=False)
    prompt=apply_chat_template(processor,model.config,PROMPT,num_images=1)
    response=generate(model,processor,prompt,image=[job['prepared_path']],max_tokens=600,
                      temperature=0,max_pixels=1572864,verbose=False)
    raw=response.text
    try:
        if hashlib.sha256(Path(job['prepared_path']).read_bytes()).hexdigest()!=job['recipe']['prepared_sha256']:
            raise ValueError('Prepared image changed during visual inference')
        if response.generation_tokens>=600: raise ValueError('Capped visual output')
        fields=parse_response(raw)
        record={k:fields.get(k) for k in ('merchant','date','total','currency')}
        record.update(source={'local_path':job['source_local_path']},sha256=job['source_sha256'],
                      visual_evidence={k:fields.get(k+'_evidence') for k in ('merchant','date','total')},
                      document_type=fields.get('document_type'))
        result={'state':'complete','record':record}
    except Exception as exc:
        result={'state':'failed','error':str(exc)}
    result.update(raw_response=raw,elapsed_s=time.monotonic()-started,recipe=job['recipe'])
    Path(job['output_path']).write_text(json.dumps(result,ensure_ascii=False,indent=2))
    mx.clear_cache()


if __name__=='__main__':main()
