"""One resident U2 model verifies core-field pixels selected without annotations."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ocr_ensemble import CACHE,EXISTING,MLX,environment,sha
from focused_ocr import prepare_focus
from ocr_view_retry import prepare_readable_focus
os.environ.update(environment())
sys.path.insert(0,str(EXISTING))
from integrity import verify_u2_model
from u2_output import parse_output,has_text
from PIL import Image

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--manifest',default='research/sample_100_manifest.json')
    parser.add_argument('--ids',nargs='*')
    parser.add_argument('--images',nargs='+',help='Already prepared detail views; do not crop or read a reference file')
    parser.add_argument('--out',help='Required output directory with --images')
    args=parser.parse_args()
    if args.images and not args.out: parser.error('--images requires --out')
    manifest=[] if args.images else json.loads((ROOT/args.manifest).read_text())
    if args.ids: manifest=[r for r in manifest if r['id'] in args.ids]
    out=CACHE/'unlimited_focus'; out.mkdir(parents=True,exist_ok=True)
    focus_dir=CACHE/'focus'; focus_dir.mkdir(exist_ok=True)
    model_path=MLX/'models/u2'
    verify_u2_model(model_path,json.loads((EXISTING/'u2-manifest.json').read_text()))
    from mlx_vlm import apply_chat_template,generate,load
    import mlx.core as mx
    model,processor=load(str(model_path),trust_remote_code=False)
    print('model loaded',flush=True)
    def infer(image,target,max_tokens,**metadata):
        started=time.monotonic(); mx.reset_peak_memory()
        prompt=apply_chat_template(processor,model.config,'Multi page parsing.',num_images=1)
        result=generate(model,processor,prompt,image=[str(image)],max_tokens=max_tokens,temperature=0)
        with Image.open(image) as im: image_size=list(im.size)
        blocks,parse_warnings=parse_output(result.text)
        record={'engine':'Unlimited-OCR-2-MLX-BF16','input_sha256':sha(image),
                'image_size':image_size,'coordinate_space':'normalized-1000',
                'blocks':blocks,'raw':result.text,'parse_warnings':parse_warnings,'geometry_valid':not parse_warnings,
                'capped':result.generation_tokens>=max_tokens,'tokens':result.generation_tokens,
                'seconds':time.monotonic()-started,'mlx_peak_bytes':mx.get_peak_memory(),**metadata}
        target.parent.mkdir(parents=True,exist_ok=True)
        tmp=target.with_suffix('.json.tmp'); tmp.write_text(json.dumps(record,ensure_ascii=False,indent=2)); tmp.replace(target)
        print(target.stem,record.get('variant','full'),record['tokens'],round(record['seconds'],2),'capped',record['capped'],'has_text',bool(has_text(record)),flush=True)
        return record
    if args.images:
        destination=ROOT/args.out
        for name in args.images:
            image=ROOT/name; target=destination/(image.stem+'.json')
            cached=json.loads(target.read_text()) if target.exists() else {}
            if cached.get('input_sha256')==sha(image) and not cached.get('capped') and has_text(cached):
                print(image.stem,'detail cache reused',flush=True);continue
            infer(image,target,4096,variant='detail')
        print('completed detail views',len(args.images),flush=True)
        return
    for item in manifest:
        rid=item['id']; image=CACHE/'oriented'/(rid+'.png')
        paddle_path=CACHE/'paddle'/(rid+'.json')
        wait_started=time.monotonic()
        while not image.exists() or not paddle_path.exists():
            if time.monotonic()-wait_started>900: raise RuntimeError(f'Paddle input missing for {rid}')
            time.sleep(2)
        source_hash=sha(image)
        full_path=CACHE/'unlimited'/(rid+'.json')
        full=json.loads(full_path.read_text()) if full_path.exists() else {}
        if full.get('input_sha256')==source_hash and not full.get('capped') and has_text(full):
            print(rid,'full cache reused',flush=True); continue
        target=out/(rid+'.json')
        cached=json.loads(target.read_text()) if target.exists() else {}
        if cached.get('source_input_sha256')==source_hash and not cached.get('capped') and not cached.get('parse_warnings') and has_text(cached):
            print(rid,'focus cache reused',flush=True); continue
        if cached.get('source_input_sha256')==source_hash:
            record=cached
        else:
            paddle=json.loads(paddle_path.read_text())
            focus=focus_dir/(rid+'.png')
            metadata=prepare_focus(image,paddle,focus)
            record=infer(focus,target,2048,variant='focus',source_input_sha256=source_hash,focus=metadata)
        if record.get('capped') or not has_text(record) or record.get('parse_warnings'):
            reason='focus_truncated' if record.get('capped') else ('focus_invalid_geometry' if record.get('parse_warnings') else 'focus_no_text')
            full_result=full if full.get('input_sha256')==source_hash else infer(image,full_path,4096,variant='full',fallback_reason=reason)
            if full_result.get('capped') or not has_text(full_result):
                readable=CACHE/'focus_enlarged'/(rid+'.png')
                metadata=prepare_readable_focus(image,json.loads(paddle_path.read_text()),readable)
                archive=CACHE/'unlimited_focus_attempts'/rid
                archive.mkdir(parents=True,exist_ok=True)
                if target.exists():
                    history=archive/(sha(target)+'.json')
                    if not history.exists():history.write_bytes(target.read_bytes())
                infer(readable,target,4096,variant='focus',preprocessing_variant='readable_focus',
                      source_input_sha256=source_hash,focus=metadata,fallback_reason='full_and_focus_incomplete')
    print('completed',len(manifest),flush=True)

if __name__=='__main__': main()
