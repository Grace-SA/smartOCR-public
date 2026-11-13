"""Direct, offline OXR recognition when layout detection skips receipt photos.

Uses the pinned OXR model and upstream recognition prompts, without calling
D-FINE or synthesizing layout. Each output block covers the entire supplied
image; it does not claim word/line localization. No reference fields are read.
"""
import argparse
import ast
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ocr_ensemble import EXISTING, MLX, environment

SOURCE_REVISION = 'b2ee4ac12ed220bf7fefa74951babf0d3b05e766'
MODEL_REVISION = 'bdbec15bad81efe04ff0e66f20d36931cce2340a'
PROMPT_NAMES = {'text': 'PROMPT_TEXT_RECOGNITION', 'table': 'PROMPT_TABLE_RECOGNITION',
                'whole_page': 'PROMPT_WHOLE_PAGE_RECOGNITION'}


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load_upstream_prompt(source, task):
    """Read the literal prompt from verified upstream, without importing clients."""
    name = PROMPT_NAMES[task]
    path = Path(source)/'oxr/model/prompts.py'
    for node in ast.parse(path.read_text(encoding='utf-8')).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            value = ast.literal_eval(node.value)
            if isinstance(value, str) and value.strip():
                return value
    raise ValueError(f'Pinned upstream recognition prompt missing: {name}')


def input_provenance(image_path):
    """Bind a derived image to its actual source; reject stale sidecar metadata."""
    image_path = Path(image_path).resolve()
    digest = sha(image_path)
    with Image.open(image_path) as image:
        size = list(image.size)
    sidecars = [(kind, image_path.with_suffix(f'.{kind}.json')) for kind in ('focus', 'detail')]
    present = [(kind, path) for kind, path in sidecars if path.is_file()]
    if len(present) > 1:
        raise ValueError('Ambiguous input: both focus and detail provenance sidecars exist')
    provenance = {'input_path': str(image_path), 'input_sha256': digest, 'image_size': size,
                  'source_input_sha256': digest, 'variant': 'full'}
    if not present:
        return provenance
    kind, sidecar = present[0]
    meta = json.loads(sidecar.read_text(encoding='utf-8'))
    if meta.get('output_sha256') != digest:
        raise ValueError('Derived image hash does not match its provenance')
    recorded_path = Path(meta.get('output_path', ''))
    recorded_path = recorded_path if recorded_path.is_absolute() else ROOT/recorded_path
    if recorded_path.resolve() != image_path or meta.get('output_size') != size:
        raise ValueError('Derived image path/size does not match its provenance')
    source_path = Path(meta.get('source_path', ''))
    source_path = source_path if source_path.is_absolute() else ROOT/source_path
    if not source_path.is_file() or meta.get('source_sha256') != sha(source_path):
        raise ValueError('Derived view source image is missing or has changed')
    if kind == 'focus' and not meta.get('regions'):
        raise ValueError('Focus provenance has no source mapping')
    if kind == 'detail' and not meta.get('source_bbox'):
        raise ValueError('Detail provenance has no source mapping')
    provenance.update(variant=kind, source_input_sha256=meta['source_sha256'])
    provenance[kind] = meta
    if kind == 'detail':
        provenance['field'] = meta.get('field')
    provenance['preprocessing_variant'] = ('readable_focus' if meta.get('variant') == 'readable_focus_retry'
                                            else ('original_focus' if kind == 'focus' else meta.get('variant', 'rgb')))
    return provenance


def recognize_image(image_path, *, model, processor, generate, apply_chat_template,
                    mx, prompt, task='text', max_tokens=4096, repetition_penalty=1.0):
    """One real model call; preserve raw response and measured generation tokens."""
    if task not in PROMPT_NAMES or not 1 <= max_tokens <= 8192:
        raise ValueError('Invalid direct recognition task or token limit')
    if not math.isfinite(repetition_penalty) or not 1.0 <= repetition_penalty <= 1.25:
        raise ValueError('Repetition penalty must be between 1.0 and 1.25')
    provenance = input_provenance(image_path)
    with Image.open(image_path) as original:
        image = original.convert('RGB')
    formatted = apply_chat_template(processor, model.config, prompt, num_images=1)
    mx.reset_peak_memory()
    started = time.monotonic()
    result = generate(model, processor, formatted, image=[image], max_tokens=max_tokens,
                      temperature=0.0, top_p=1.0, repetition_penalty=repetition_penalty)
    elapsed = time.monotonic()-started
    if not isinstance(result.text, str) or not isinstance(result.generation_tokens, int) or result.generation_tokens < 0:
        raise ValueError('Model did not return genuine text and generation-token accounting')
    tokens = result.generation_tokens
    capped = tokens >= max_tokens
    width, height = provenance['image_size']
    prompt_sha = hashlib.sha256(prompt.encode('utf-8')).hexdigest()
    call = {'tokens': tokens, 'capped': capped, 'max_tokens': max_tokens, 'seconds': elapsed,
            'task': task, 'prompt_sha256': prompt_sha, 'temperature': 0.0, 'top_p': 1.0,
            'repetition_penalty': repetition_penalty,
            'finish_reason': 'length' if capped else 'model_terminated'}
    prompt_tokens = getattr(result, 'prompt_tokens', None)
    if prompt_tokens is not None:
        call['prompt_tokens'] = int(prompt_tokens)
    # Whole-region geometry is honest: the direct text task supplies no boxes.
    blocks = ([{'label': 'table' if task == 'table' else 'text', 'content': result.text,
                'bbox': [0, 0, width, height], 'page': 1, 'geometry_scope': 'whole_input'}]
              if result.text.strip() else [])
    return {'engine': 'SoMark-OXR-1.0-MLX-BF16', 'source_revision': SOURCE_REVISION,
            'model_revision': MODEL_REVISION, 'adapter_version': 1,
            'adapter_source_sha256': sha(__file__), **provenance,
            'recognition_variant': 'direct_'+task, 'independent_model_vote': False,
            'layout_bypassed': True, 'layout_calls': 0,
            'coordinate_space': 'pixels', 'geometry_scope': 'whole_input',
            'blocks': blocks, 'raw': result.text, 'capped': capped, 'tokens': tokens,
            'calls': [call], 'seconds': elapsed, 'mlx_peak_bytes': int(mx.get_peak_memory()),
            'prompt': prompt, 'prompt_sha256': prompt_sha,
            'limitations': ['Direct recognition does not predict word or line bounding boxes.',
                            'This is the same OXR model; alternate views do not add independent votes.']}


def write_record(target, record):
    """Keep exact previous bytes before atomically publishing a new response."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        archive = target.parent/'attempts'/target.stem/(sha(target)+'.json')
        archive.parent.mkdir(parents=True, exist_ok=True)
        if not archive.exists():
            archive.write_bytes(target.read_bytes())
    temporary = target.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(target)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--images', type=Path, nargs='+', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--task', choices=tuple(PROMPT_NAMES), default='text')
    parser.add_argument('--max-tokens', type=int, default=4096)
    parser.add_argument('--repetition-penalty', type=float, default=1.0,
                        help='Default matches pinned upstream; optionally use a mild penalty up to 1.25')
    args = parser.parse_args(argv)
    if not 1 <= args.max_tokens <= 8192:
        parser.error('--max-tokens must be between 1 and 8192')
    if not math.isfinite(args.repetition_penalty) or not 1.0 <= args.repetition_penalty <= 1.25:
        parser.error('--repetition-penalty must be between 1.0 and 1.25')
    if len({image.stem for image in args.images}) != len(args.images):
        parser.error('Input image stems must be unique within a batch')
    # Validate all image provenance before loading expensive model weights.
    for image in args.images:
        input_provenance(image)
    os.environ.update(environment())
    source = Path(os.environ['SMARTPPT_OXR_SOURCE'])
    model_dir = Path(os.environ['SMARTPPT_OXR_MODEL'])
    manifest = json.loads((EXISTING/'oxr-manifest.json').read_text())
    if manifest.get('source_revision') != SOURCE_REVISION or manifest.get('model_revision') != MODEL_REVISION:
        raise ValueError('The direct runner requires the pinned OXR source and model revisions')
    sys.path.insert(0, str(EXISTING))
    from integrity import verify_files
    verify_files(source, manifest['source_files'])
    verify_files(model_dir, manifest['model_files'])
    prompt = load_upstream_prompt(source, args.task)
    # Imports are deliberately lazy so --help and unit tests never start Metal.
    import mlx.core as mx
    from mlx_vlm import apply_chat_template, generate, load
    model, processor = load(str(model_dir), trust_remote_code=False)
    print('OXR direct model loaded; layout detection bypassed', flush=True)
    for image in args.images:
        record = recognize_image(image, model=model, processor=processor, generate=generate,
                                 apply_chat_template=apply_chat_template, mx=mx, prompt=prompt,
                                 task=args.task, max_tokens=args.max_tokens,
                                 repetition_penalty=args.repetition_penalty)
        write_record(args.out/(image.stem+'.json'), record)
        print(image.stem, args.task, record['tokens'], round(record['seconds'], 2),
              'capped', record['capped'], 'has_text', bool(record['blocks']), flush=True)


if __name__ == '__main__':
    main()
