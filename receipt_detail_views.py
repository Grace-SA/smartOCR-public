"""Single-rectangle, traceable detail views for disputed OCR fields.

Selection uses only image dimensions and Paddle text/geometry. A detail view is
a transformation of existing evidence, never an independent sample or model.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from pathlib import Path

from PIL import Image, ImageEnhance, ImageOps

DATE = re.compile(r'\b\d{1,4}\s*[/.-]\s*\d{1,2}\s*[/.-]\s*\d{2,4}\b|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b|\bdate\b', re.I)
MONEY = re.compile(r'[-$]?\s*\d+[.,]\s*\d{2}\b')
TOTAL = re.compile(r'\b(?:t[o0]tal|amount\s*(?:due|paid)|balance\s*due)\b', re.I)
NOT_TOTAL = re.compile(r'\b(?:sub\s*total|gst|tax|change|tendered|surcharge|savings?|discount|price|points|reward|total\s+items)\b', re.I)
PAYMENT = re.compile(r'\b(?:payment|purchase|paid|eftpos|eft|visa|mastercard|cash|tendered|change|surcharge|rounding|gst)\b', re.I)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _detections(record, size):
    width,height = size
    lines=[]
    for item in record.get('lines',[]):
        text=str(item.get('text','')).strip()
        points=item.get('polygon')
        if not text or not points or float(item.get('confidence',1))<.25: continue
        try:
            xs,ys=zip(*[(float(p[0]),float(p[1])) for p in points])
            box=[max(0,math.floor(min(xs))),max(0,math.floor(min(ys))),min(width,math.ceil(max(xs))),min(height,math.ceil(max(ys)))]
        except (ValueError,TypeError,IndexError): continue
        if box[2]>box[0] and box[3]>box[1]: lines.append({'text':text,'bbox':box})
    return lines


def _rows(lines):
    groups=[]
    for line in sorted(lines,key=lambda x:(x['bbox'][1],x['bbox'][0])):
        x1,y1,x2,y2=line['bbox']; height=y2-y1
        group=None
        for existing in reversed(groups[-4:]):
            gy1,gy2=existing['y1'],existing['y2']
            overlap=max(0,min(y2,gy2)-max(y1,gy1))
            if overlap/min(height,gy2-gy1)>=.4:
                group=existing;break
        if group is None:
            groups.append({'y1':y1,'y2':y2,'items':[line]})
        else:
            group['items'].append(line);group['y1']=min(group['y1'],y1);group['y2']=max(group['y2'],y2)
    for group in groups:
        group['text']=' '.join(i['text'] for i in sorted(group['items'],key=lambda i:i['bbox'][0]))
    return groups


def _snap(start,end,lines,height,padding):
    # Expand boundaries that intersect text, rather than cutting a neighboring
    # tax/date/amount glyph in half. This never joins nonadjacent regions.
    original_start,original_end=start,end
    for line in lines:
        _,y1,_,y2=line['bbox']
        if y1<original_start<y2: start=min(start,max(0,y1-padding))
        if y1<original_end<y2: end=max(end,min(height,y2+padding))
    return max(0,int(start)),min(height,int(end))


def prepare_detail(image_path, paddle_record, field, out_path, *, variant='rgb', region_index=0):
    """Create one crop, enlarged 2x/3x where size permits, with affine mapping.

    ``field`` is merchant/date/total. ``region_index`` selects a distinct date
    anchor by source order, useful when the receipt repeats its transaction date.
    No deskew, stitching, generative enhancement, thresholding or sharpening is
    applied. The parent pipeline still has the oriented full image.
    """
    if field not in {'merchant','date','total'}: raise ValueError('Unsupported receipt field')
    if variant not in {'rgb','gray','contrast'}: raise ValueError('Unsupported view variant')
    if not isinstance(region_index,int) or region_index<0: raise ValueError('Invalid region index')
    image_path,out_path=Path(image_path),Path(out_path)
    digest=_sha(image_path)
    if paddle_record.get('input_sha256') not in (None,digest): raise ValueError('Paddle input hash mismatch')
    with Image.open(image_path) as opened: image=opened.convert('RGB')
    width,height=image.size
    if paddle_record.get('image_size') not in (None,[width,height]): raise ValueError('Paddle image dimensions mismatch')
    lines=_detections(paddle_record,image.size)
    horizontal=[i for i in lines if i['bbox'][2]-i['bbox'][0]>=i['bbox'][3]-i['bbox'][1]]
    rows=_rows(horizontal)
    line_height=max(8,statistics.median(i['bbox'][3]-i['bbox'][1] for i in horizontal)) if horizontal else max(12,height/50)
    anchors=[];warnings=[];source_selection=''
    if field=='merchant':
        # Full source width is intentional: undetected logos may extend beyond
        # the text detector's bounding rectangle.
        end=max(height*.25, max((r['y2'] for r in rows[:6]),default=0)+line_height*.5)
        start,end=0,min(height,max(height*.25,min(end,height*.42)))
        table_header=next((r for r in rows if re.search(r'^\s*(?:ITEM|DESCRIPTION|PRODUCT|QTY|QUANTITY)\b',r['text'],re.I)),None)
        if table_header and table_header['y1']>height*.10:
            end=min(end,max(line_height,table_header['y1']-line_height*.4))
        source_selection='source header, including logo and first text rows'
        anchors=[{'text':r['text'],'bbox':[0,r['y1'],width,r['y2']]} for r in rows if r['y1']<end]
    elif field=='date':
        dates=[r for r in rows if DATE.search(r['text']) and not re.search(r'expir|best\s*before|valid\s*until|warranty',r['text'],re.I)]
        # An explicit Date label ranks above an unlabeled terminal reprint.
        dates.sort(key=lambda r:(not bool(re.search(r'\bdate\b',r['text'],re.I)),r['y1']))
        if dates:
            if region_index>=len(dates): raise ValueError('Requested date region does not exist')
            anchor=dates[region_index]
            start,end=anchor['y1']-line_height*2,anchor['y2']+line_height*2
            anchors=[{'text':anchor['text'],'bbox':[0,anchor['y1'],width,anchor['y2']]}]
            source_selection='date anchor with adjacent transaction context'
        else:
            start,end=height*.55,height
            warnings.append('No date anchor detected; bottom region is only a fallback, not date evidence')
            source_selection='bottom fallback without date evidence'
    else:
        totals=[r for r in rows if TOTAL.search(r['text']) and not NOT_TOTAL.search(r['text'])]
        payments=[r for r in rows if PAYMENT.search(r['text']) and MONEY.search(r['text'])]
        if totals:
            first,last=min(r['y1'] for r in totals),max(r['y2'] for r in totals)
            # Include adjacent EFT/PURCHASE/tax/rounding/total rows, but do not
            # drag an item-table column titled TOTAL into the financial crop.
            related=[r for r in payments if r['y2']>=first-line_height*3 and r['y1']<=last+line_height*9]
            selected=totals+related
            start=min(r['y1'] for r in selected)-line_height*2
            end=max(r['y2'] for r in selected)+line_height*2
            anchors=[{'text':r['text'],'bbox':[0,r['y1'],width,r['y2']]} for r in selected]
            source_selection='overall total and surrounding payment/tax context'
        elif payments:
            selected=[r for r in payments if r['y1']>=height*.35] or payments
            start=min(r['y1'] for r in selected)-line_height*3
            end=max(r['y2'] for r in selected)+line_height*2
            anchors=[{'text':r['text'],'bbox':[0,r['y1'],width,r['y2']]} for r in selected]
            source_selection='payment-context fallback without explicit total'
            warnings.append('No explicit overall total anchor; payment values still require semantic validation')
        else:
            start,end=height*.50,height
            source_selection='bottom fallback without financial anchor'
            warnings.append('No total or payment anchor detected; crop does not establish a value')
    start,end=_snap(max(0,math.floor(start)),min(height,math.ceil(end)),horizontal,height,math.ceil(line_height*.25))
    if end<=start: raise ValueError('Empty detail crop')
    box=[0,start,width,end]
    cropped=image.crop(box)
    desired_scale=3 if max(cropped.size)<=1024 else 2
    scale=min(desired_scale,6144/max(cropped.size))
    scale=max(1,scale)
    output_size=(round(cropped.width*scale),round(cropped.height*scale))
    if variant=='gray': cropped=ImageOps.grayscale(cropped).convert('RGB')
    elif variant=='contrast': cropped=ImageEnhance.Contrast(cropped).enhance(1.15)
    output=cropped.resize(output_size,Image.Resampling.LANCZOS)
    out_path.parent.mkdir(parents=True,exist_ok=True)
    output.save(out_path,format='PNG')
    sx,sy=output_size[0]/cropped.width,output_size[1]/cropped.height
    result={'version':1,'field':field,'variant':variant,'derived_view':True,'independent_sample':False,
            'source_path':str(image_path.resolve()),'source_sha256':digest,'source_size':[width,height],
            'source_bbox':box,'output_path':str(out_path.resolve()),'output_sha256':_sha(out_path),
            'output_size':list(output_size),'scale':scale,'scale_x':sx,'scale_y':sy,
            'source_to_output_affine':[sx,0,-box[0]*sx,0,sy,-box[1]*sy],
            'output_to_source_affine':[1/sx,0,box[0],0,1/sy,box[1]],
            'selection':source_selection,'anchors':anchors,'warnings':warnings,
            'transform':'single source rectangle; Lanczos interpolation; '+variant,
            'limitations':['Upsampling does not restore missing source information.',
                           'A result from this view is correlated with full-image OCR from the same model.',
                           'All output coordinates map to one source rectangle; no disconnected rows are joined.']}
    out_path.with_suffix('.detail.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result
