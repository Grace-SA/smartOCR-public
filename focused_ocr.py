"""Pixel-preserving receipt focus views with explicit source-coordinate provenance.

This is a second view for corroborating merchant/date/total, never a replacement
for the full-image OCR. No annotation values, merchant registry or filenames
participate in region selection.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from pathlib import Path

from PIL import Image

DATE = re.compile(r'\b\d{1,4}\s*[/.-]\s*\d{1,2}\s*[/.-]\s*\d{2,4}\b|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b|\bdate\b', re.I)
TOTAL = re.compile(r'\b(?:t[o0]tal|sub\s*total|amount|balance|invoice\s*total)\b', re.I)
PAYMENT = re.compile(r'\b(?:payment|purchase|paid|eftpos|eft|visa|mastercard|cash|tendered|change|surcharge|rounding|gst)\b', re.I)


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _lines(record, width, height):
    result = []
    for item in record.get('lines', []):
        points = item.get('polygon')
        text = str(item.get('text', '')).strip()
        if not points or not text or float(item.get('confidence', 1)) < .25:
            continue
        try:
            xs, ys = zip(*[(float(p[0]), float(p[1])) for p in points])
            box = [max(0, math.floor(min(xs))), max(0, math.floor(min(ys))),
                   min(width, math.ceil(max(xs))), min(height, math.ceil(max(ys)))]
        except (ValueError, TypeError, IndexError):
            continue
        if box[2] > box[0] and box[3] > box[1]:
            result.append({'text': text, 'box': box})
    return result


def _merge(spans, gap):
    merged = []
    for start, end, reasons in sorted(spans, key=lambda item: (item[0], item[1])):
        if merged and start <= merged[-1][1] + gap:
            merged[-1][1] = max(end, merged[-1][1])
            merged[-1][2].update(reasons)
        else:
            merged.append([start, end, set(reasons)])
    return merged


def prepare_focus(image_path, paddle_record, out_path):
    """Write a PNG focus image and ``.focus.json`` source-to-view crop map.

    Retains original RGB pixels with no scale/rotation/contrast changes. Only
    white separators are introduced. Geometry is relative to ``image_path``,
    normally the separately oriented full image, not the original camera file.
    """
    image_path, out_path = Path(image_path), Path(out_path)
    digest = _hash(image_path)
    if paddle_record.get('input_sha256') not in (None, digest):
        raise ValueError('Paddle evidence belongs to a different image')
    with Image.open(image_path) as original:
        image = original.convert('RGB')
    width, height = image.size
    if paddle_record.get('image_size') not in (None, [width, height]):
        raise ValueError('Paddle geometry size does not match source image')
    lines = _lines(paddle_record, width, height)
    warnings = []
    anchors = []
    vertical = sum((i['box'][3]-i['box'][1]) > (i['box'][2]-i['box'][0])*1.5 for i in lines)
    if len(lines) < 4 or vertical > max(4, len(lines)*.30):
        # Cropping uncertain orientation or sparse OCR could silently remove facts.
        regions = [[0, height, {'full_image_fallback'}]]
        x0, x1, line_height = 0, width, 16
        warnings.append('Sparse detections or uncertain orientation: full source retained')
    else:
        horizontal = [i for i in lines if i['box'][2]-i['box'][0] >= i['box'][3]-i['box'][1]]
        line_height = max(8, statistics.median(i['box'][3]-i['box'][1] for i in horizontal or lines))
        margin = max(12, math.ceil(line_height*.7))
        x0 = max(0, min(i['box'][0] for i in lines)-margin)
        x1 = min(width, max(i['box'][2] for i in lines)+margin)
        ordered = sorted(horizontal or lines, key=lambda i: (i['box'][1], i['box'][0]))
        # Header includes logo pixels above the first recognized text and at least
        # six text rows. Count geometric rows rather than right-hand price boxes.
        row_ends = []
        last_y = None
        for item in ordered:
            y = item['box'][1]
            if last_y is None or y-last_y > line_height*.6:
                row_ends.append(item['box'][3]); last_y = y
            if len(row_ends) >= 6: break
        first_y = min(i['box'][1] for i in lines)
        header_end = min(height, math.ceil(max(height*.15, max(row_ends))+line_height))
        spans = [[0, header_end, {'header'}]]
        found_date = found_total = False
        for item in lines:
            text, box = item['text'], item['box']
            reasons = set()
            if DATE.search(text): reasons.add('date'); found_date = True
            if TOTAL.search(text): reasons.add('total'); found_total = True
            if PAYMENT.search(text): reasons.add('payment_context')
            if not reasons: continue
            # Context includes neighboring monetary lines to distinguish final
            # totals from GST, surcharge, tendered cash and change.
            padding = line_height*(2.2 if reasons & {'total','payment_context'} else 1.25)
            start, end = max(0, math.floor(box[1]-padding)), min(height, math.ceil(box[3]+padding))
            spans.append([start, end, reasons])
            anchors.append({'text': text, 'source_bbox': box, 'reasons': sorted(reasons)})
        if not found_total or not found_date:
            spans.append([math.floor(height*.60), height, {'tail_fallback'}])
            warnings.append('No date or total anchor detected: bottom 40% retained as fallback')
        regions = _merge(spans, line_height*.6)
        retained = sum(end-start for start,end,_ in regions)
        if retained >= height*.92:
            regions = [[0, height, {'full_image_low_savings'}]]
    gap = max(12, math.ceil(line_height*.7))
    output_height = sum(end-start for start,end,_ in regions)+gap*(len(regions)-1)
    canvas = Image.new('RGB', (x1-x0, output_height), 'white')
    mapping = []
    offset = 0
    for start,end,reasons in regions:
        tile = image.crop((x0,start,x1,end))
        canvas.paste(tile,(0,offset))
        mapping.append({'source_bbox':[x0,start,x1,end], 'focus_bbox':[0,offset,x1-x0,offset+end-start], 'reasons':sorted(reasons)})
        offset += end-start+gap
    out_path.parent.mkdir(parents=True,exist_ok=True)
    canvas.save(out_path,format='PNG')
    metadata = {'version':1,'source_path':str(image_path.resolve()),'source_sha256':digest,
                'output_path':str(out_path.resolve()),'output_sha256':_hash(out_path),
                'source_size':[width,height],'output_size':list(canvas.size),
                'retained_pixel_fraction':round(sum((b['source_bbox'][2]-b['source_bbox'][0])*(b['source_bbox'][3]-b['source_bbox'][1]) for b in mapping)/(width*height),4),
                'regions':mapping,'anchors':anchors,'white_separator_height':gap,
                'warnings':warnings,'method':'original RGB pixels; crops and white padding only',
                'limitations':['Focus is additional evidence, not a substitute for full-image OCR.',
                               'A model may confuse disjoint sections; use crop mapping when grounding evidence.',
                               'Missing or covered source fields cannot be recovered by this transform.']}
    out_path.with_suffix('.focus.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    return metadata
