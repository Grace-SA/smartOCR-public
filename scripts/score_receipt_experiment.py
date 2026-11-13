"""Score saved outputs only. Never supplies annotations to an OCR process."""
import argparse
from collections import Counter
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import statistics


def key(field, value):
    if value is None or value in ('待识别商家','Unknown merchant'):
        return None
    if field == 'merchant':
        return re.sub(r'[^a-z0-9]', '', str(value).lower().replace('&','and'))
    if field == 'total':
        return str(Decimal(str(value)).quantize(Decimal('.01')))
    return str(value)


def score(experiment, reference):
    references = json.loads(reference.read_text())
    rows, times = [], []
    counts = {f: Counter() for f in ('merchant','date','total')}
    for ref in references:
        path = experiment/(ref['id']+'.json')
        saved = json.loads(path.read_text()) if path.exists() else {'state':'not_processed','record':{}}
        prediction = saved.get('record', {})
        match = {}
        for field in counts:
            actual = key(field, prediction.get(field))
            if ref[field] is None:
                counts[field]['unreadable_reference'] += 1
                counts[field]['correct_abstentions'] += actual is None
                counts[field]['unsupported_populated'] += actual is not None
                match[field] = None
            else:
                expected = key(field, ref[field])
                counts[field]['visible_reference'] += 1
                counts[field]['strict_correct'] += actual == expected
                aliases = [expected] + [key(field,a) for a in ref.get('merchant_aliases',[])] if field == 'merchant' else [expected]
                match[field] = actual in aliases
                counts[field]['accepted_correct'] += match[field]
                counts[field]['missing'] += actual is None
        if 'elapsed_s' in saved:
            times.append(saved['elapsed_s'])
        rows.append({'id':ref['id'],'state':saved['state'],'match':match,
                     'complete_reference':all(ref[f] is not None for f in counts),
                     'all_correct':all(match.values()), 'automatic':prediction.get('status')=='auto_confirmed',
                     'elapsed_s':saved.get('elapsed_s')})
    ordered = sorted(times)
    p95 = ordered[min(len(ordered)-1, max(0, __import__('math').ceil(len(ordered)*.95)-1))] if ordered else None
    return {'reference_sha256':hashlib.sha256(reference.read_bytes()).hexdigest(),
            'denominator':len(references),'completed':sum(r['state']=='complete' for r in rows),
            'fields':{f:dict(v) for f,v in counts.items()},'complete_reference_count':sum(r['complete_reference'] for r in rows),
            'all_correct':sum(r['all_correct'] for r in rows),
            'automatic_count':sum(r['automatic'] for r in rows),
            'automatic_nonmatches':sum(r['automatic'] and not r['all_correct'] for r in rows),
            'timing_s':{'sum':sum(times),'median':statistics.median(times) if times else None,'p95_nearest_rank':p95},
            'limitations':'Small deliberately selected development pilot; assistant visual references, not independent human gold. Missing-reference fields are reported as abstention controls, never counted as correct extraction. Merchant aliases were fixed before inference.',
            'rows':rows}


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('experiment',type=Path)
    p.add_argument('--reference',required=True,type=Path)
    args=p.parse_args()
    result=score(args.experiment,args.reference)
    (args.experiment/'evaluation.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},indent=2))
