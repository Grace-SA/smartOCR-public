"""Evidence-preserving readable-focus retry for OCR models that skip photos.

This only changes the presentation of existing pixels. It cannot reconstruct
missing text, and its result is a derived view of the same receipt.
"""
import hashlib
import json
import tempfile
from pathlib import Path

from PIL import Image, ImageOps

from focused_ocr import prepare_focus


_ORIGINAL_FOCUS_DIR = Path(__file__).resolve().parent / 'data/ensemble/focus'
_BORDER = 32


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare_readable_focus(image_path, paddle_record, out_path):
    """Save a new PNG and ``.focus.json`` with exact original-to-view mapping.

    The source is the oriented full image associated with ``paddle_record``.
    Existing ordinary-focus images are protected. All crop decisions are made
    by ``prepare_focus`` from image geometry and Paddle text, never filenames.
    Coordinates are pixel edges; each region has its own affine transform.
    """
    image_path, out_path = Path(image_path).resolve(), Path(out_path).resolve()
    protected = _ORIGINAL_FOCUS_DIR.resolve()
    if out_path == protected or protected in out_path.parents:
        raise ValueError('Readable retries must not overwrite the original focus cache')
    sidecar = out_path.with_suffix('.focus.json')
    for candidate in (out_path, sidecar):
        if candidate == image_path or (candidate.exists() and candidate.samefile(image_path)):
            raise ValueError('A derived view must not overwrite its source image')
    if out_path.suffix.lower() != '.png':
        raise ValueError('Readable focus output must use a separate .png path')

    # Never read or replace the existing focus cache: even the intermediate is
    # freshly generated from the verified full image and current detections.
    with tempfile.TemporaryDirectory(prefix='receipt-readable-focus-') as temporary:
        base_path = Path(temporary) / 'base.png'
        base = prepare_focus(image_path, paddle_record, base_path)
        with Image.open(base_path) as opened:
            gray = ImageOps.grayscale(opened)
        base_size = gray.size
        adjusted = ImageOps.autocontrast(gray, cutoff=0.25)
        # Blend half the adjustment back into the original luminance to avoid
        # aggressive thresholding or amplifying faint background artifacts.
        readable = Image.blend(gray, adjusted, 0.5)
        scale = 3 if max(base_size) <= 1100 else 2
        enlarged_size = (base_size[0] * scale, base_size[1] * scale)
        enlarged = readable.resize(enlarged_size, Image.Resampling.LANCZOS)
        output = ImageOps.expand(enlarged, border=_BORDER, fill=255).convert('RGB')

    regions = []
    for region in base['regions']:
        sx0, sy0, sx1, sy1 = region['source_bbox']
        bx0, by0, bx1, by1 = region['focus_bbox']
        fx0, fy0, fx1, fy1 = [v * scale + _BORDER for v in (bx0, by0, bx1, by1)]
        regions.append({
            **region,
            'base_focus_bbox': list(region['focus_bbox']),
            'focus_bbox': [fx0, fy0, fx1, fy1],
            'source_to_focus_affine': [scale, 0, fx0-sx0*scale, 0, scale, fy0-sy0*scale],
            'focus_to_source_affine': [1/scale, 0, sx0-fx0/scale, 0, 1/scale, sy0-fy0/scale],
        })
    out_path.parent.mkdir(parents=True, exist_ok=True)
    output.save(out_path, format='PNG')
    metadata = {
        **base,
        'version': 2,
        'derived_view': True,
        'independent_sample': False,
        'variant': 'readable_focus_retry',
        'output_path': str(out_path),
        'output_sha256': _hash(out_path),
        'image_size': list(output.size),
        'output_size': list(output.size),
        'base_focus_size': list(base_size),
        'base_focus_sha256': base['output_sha256'],
        'scale': scale,
        'scale_x': scale,
        'scale_y': scale,
        'border_pixels': _BORDER,
        'regions': regions,
        'white_separator_height': base['white_separator_height'] * scale,
        'method': 'Paddle-guided source crops; grayscale; mild autocontrast; Lanczos enlargement; white border',
        'preprocessing': {
            'crop_method': base['method'],
            'grayscale': True,
            'autocontrast_cutoff_percent': 0.25,
            'autocontrast_blend': 0.5,
            'resize_filter': 'Lanczos',
            'scale': scale,
            'white_border_pixels': _BORDER,
            'rotation_degrees': 0,
            'sharpening': False,
            'generated_text': False,
        },
        'limitations': base['limitations'] + [
            'Contrast and interpolation only change presentation; they add no source evidence.',
            'This view is the same receipt; a retry from the same model is not an independent vote.',
            'Only each mapped region corresponds to original pixels; separators and border are padding.',
        ],
    }
    sidecar.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    return metadata
