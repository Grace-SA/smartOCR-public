"""Score saved first-pass predictions only; never run OCR or repair a prediction."""
import argparse
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
from html import escape
import json
import math
from pathlib import Path
import re
import statistics

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'research/blind100'
FIELDS = ('merchant', 'date', 'total')


def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path): return json.loads(path.read_text())
def merchant_key(value): return re.sub(r'[^a-z0-9]', '', str(value or '').lower().replace('&', ' and '))


def compare(actual, expected, field):
    if expected is None: return None
    if actual is None or isinstance(actual, bool): return False
    if field == 'merchant': return merchant_key(actual) == merchant_key(expected)
    if field == 'total':
        try: return Decimal(str(actual)).quantize(Decimal('.01')) == Decimal(str(expected)).quantize(Decimal('.01'))
        except InvalidOperation: return False
    return actual == expected


def percentile(values, q):
    return sorted(values)[max(0, math.ceil(len(values) * q) - 1)] if values else None


def score(allow_partial=False):
    manifest = read(BASE / 'manifest.json')
    if not allow_partial and len(manifest) != 100: raise ValueError('Exactly 100 selected images required')
    # Hash every saved prediction and run before opening independent answers.
    frozen_predictions = {}
    for item in manifest:
        path = BASE / 'predictions' / (item['id'] + '.json')
        run_path = BASE / 'runs' / (item['id'] + '.json')
        if not run_path.exists():
            if allow_partial: continue
            raise ValueError('First pass is not complete: ' + item['id'])
        run = read(run_path)
        if run['image_sha256'] != item['sha256']: raise ValueError('Input changed: ' + item['id'])
        frozen_predictions[item['id']] = {'prediction': read(path) if path.exists() else {}, 'run': run,
                                          'prediction_sha256': digest(path) if path.exists() else None,
                                          'run_sha256': digest(run_path)}
    references = {r['id']: r for r in read(BASE / 'references.json')}
    rows = []
    for item in manifest:
        if item['id'] not in frozen_predictions: continue
        frozen = frozen_predictions[item['id']]
        pred, run = frozen['prediction'], frozen['run']
        ref = references.get(item['id'], {})
        checks = {field: compare(pred.get(field), ref.get(field), field) for field in FIELDS}
        complete_reference = all(check is not None for check in checks.values())
        core_correct = complete_reference and all(checks.values())
        all_three = all(pred.get('ocr_engines', {}).get(e, {}).get('recognition_complete') for e in ('paddle', 'unlimited', 'oxr'))
        rows.append({'id': item['id'], 'image_path': item.get('local_path') or item.get('path'),
                     'image_sha256': item['sha256'], 'prediction_sha256': frozen['prediction_sha256'],
                     'source_url': item.get('source_url') or item.get('source_page_url'),
                     'expected': {f: ref.get(f) for f in FIELDS}, 'actual': {f: pred.get(f) for f in FIELDS},
                     'field_matches': checks, 'reference_complete': complete_reference,
                     'reference_uncertainty': ref.get('uncertainty', []), 'core_correct': core_correct,
                     'all_three_complete': all_three, 'status': pred.get('status', 'processing_failed'),
                     'auto_confirmed': pred.get('status') == 'auto_confirmed', 'confidence': pred.get('confidence'),
                     'wall_seconds': run['wall_seconds'], 'pipeline_seconds': pred.get('blind_timing', {}).get('ocr_pipeline_seconds'),
                     'model_timing': {e: {k: v for k, v in value.items() if 'time' in k or k.endswith('_ms')}
                                      for e, value in pred.get('ocr_engines', {}).items()},
                     'returncode': run['returncode'], 'timed_out': run['timed_out'],
                     'processing_success': run['returncode'] == 0 and bool(pred), 'run_sha256': frozen['run_sha256']})
    fields = {f: {'correct': sum(r['field_matches'][f] is True for r in rows),
                  'reference_available': sum(r['field_matches'][f] is not None for r in rows),
                  'missing_reference': sum(r['field_matches'][f] is None for r in rows)} for f in FIELDS}
    for field in fields.values():
        field['accuracy'] = field['correct'] / field['reference_available'] if field['reference_available'] else None
    auto = [r for r in rows if r['auto_confirmed']]
    auto_known = [r for r in auto if r['reference_complete']]
    timings = [r['wall_seconds'] for r in rows]
    result = {'created_at': datetime.now(timezone.utc).isoformat(), 'target_count': 100,
              'selected_count': len(manifest), 'tested_count': len(rows), 'complete': len(rows) == len(manifest) == 100,
              'manifest_sha256': digest(BASE / 'manifest.json'), 'reference_sha256': digest(BASE / 'references.json'),
              'extraction_freeze_sha256': digest(BASE / 'freeze.json'),
              'confidence_policy_sha256': digest(BASE / 'confidence_policy.py'),
              'fields': fields, 'all_core_correct': sum(r['core_correct'] for r in rows),
              'complete_reference_count': sum(r['reference_complete'] for r in rows),
              'processing_success_count': sum(r['processing_success'] for r in rows),
              'all_three_complete_count': sum(r['all_three_complete'] for r in rows),
              'automatic': {'count': len(auto), 'coverage': len(auto) / len(rows) if rows else 0,
                            'fully_scorable': len(auto_known), 'correct': sum(r['core_correct'] for r in auto_known),
                            'false_confirmations': [r['id'] for r in auto_known if not r['core_correct']],
                            'unverified_confirmations': [r['id'] for r in auto if not r['reference_complete']],
                            'precision': sum(r['core_correct'] for r in auto_known) / len(auto_known) if auto_known else None},
              'timing_seconds': {'total': sum(timings), 'mean': statistics.mean(timings) if timings else None,
                                 'median': statistics.median(timings) if timings else None,
                                 'p90': percentile(timings, .90), 'p95': percentile(timings, .95),
                                 'maximum': max(timings) if timings else None},
              'merchant_distribution': dict(Counter(r['expected']['merchant'] for r in rows)),
              'criterion': 'Exact ISO date and cent amount. Merchant ignores case, spaces and punctuation; & equals and. No aliases, fuzzy matching or corrections after seeing predictions.',
              'limitations': ['References are independent assistant visual transcriptions, not a human gold standard.',
                             'Public FOI samples overrepresent travel, transport and repeated layouts; inspect source and merchant distributions.',
                             'Accuracy and auto-confirmation precision are observed sample measurements, not a guarantee for future receipts.',
                             'Times include cold process/model loading, image preparation and existing retries; exclude downloads, annotation and AI classification.',
                             'Runs took place on a shared Mac; concurrent work in another OCR project can affect timings.'],
              'results': rows}
    out = BASE / 'evaluation.json'
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    render(result)
    print(json.dumps({k: result[k] for k in ('tested_count', 'complete', 'fields', 'all_core_correct', 'automatic', 'timing_seconds')}, indent=2))
    return result


def render(report):
    def h(value): return escape(str(value if value is not None else 'Missing'))
    def percent(value): return f'{100*value:.1f}%' if value is not None else 'Not measurable'
    rows = []
    for row in report['results']:
        cells = []
        for field in FIELDS:
            check = row['field_matches'][field]
            cells.append(f'<td class="{"ok" if check else "bad"}"><b>{h(row["actual"][field])}</b><small>Reference: {h(row["expected"][field])}</small></td>')
        rows.append(f'<tr data-failed="{str(not row["core_correct"]).lower()}" data-auto="{str(row["auto_confirmed"]).lower()}"><td><a href="/{h(row["image_path"])}" target="_blank">{h(row["id"])}</a></td>'+''.join(cells)+f'<td>{h(row["status"])}</td><td>{row["wall_seconds"]:.2f}s</td></tr>')
    cards = ''.join(f'<article><h2>{field.title()}</h2><strong>{percent(v["accuracy"])}</strong><p>{v["correct"]}/{v["reference_available"]} scored · {v["missing_reference"]} missing references</p></article>' for field, v in report['fields'].items())
    auto = report['automatic']; timing = report['timing_seconds']
    html = f'''<!doctype html><html lang="en-AU"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Blind OCR evaluation · Receipt Desk</title>
<style>body{{font:15px/1.5 system-ui;color:#183544;background:#f5f8f9;margin:0;padding:32px}}main{{max-width:1400px;margin:auto}}h1{{font-size:32px}}a{{color:#096958}}.cards{{display:flex;gap:16px;flex-wrap:wrap}}article{{background:white;padding:20px;flex:1;min-width:220px;border:1px solid #d7e2e5;border-radius:12px}}article strong{{font-size:32px}}h2{{font-size:17px}}.notice{{background:#fff1cc;padding:16px;border-radius:8px}}.table{{overflow:auto;background:white}}table{{border-collapse:collapse;width:100%}}th,td{{padding:12px;border-bottom:1px solid #ddd;text-align:left;vertical-align:top}}small{{display:block;color:#596c78}}.bad{{background:#fff0ed}}.ok{{background:#edf8f1}}select{{padding:10px;margin:16px 0}}code{{word-break:break-all}}</style><main>
<a href="/">← Receipt Desk</a><h1>Blind OCR evaluation</h1><p>{report['tested_count']} tested / {report['target_count']} requested · {'Complete' if report['complete'] else 'IN PROGRESS — incomplete sample'}</p>
<p class="notice">Frozen extraction rules and confidence policy. No new-sample corrections are included. These are sample results, not a guarantee of 100% future accuracy.</p>
<div class="cards">{cards}<article><h2>All three fields correct</h2><strong>{report['all_core_correct']}/{report['tested_count']}</strong><p>{report['complete_reference_count']} fully scorable receipts</p></article></div>
<h2>Automatic confirmation</h2><p>{auto['count']} automatically confirmed ({percent(auto['coverage'])} coverage); {percent(auto['precision'])} precision on {auto['fully_scorable']} scorable confirmations. Incorrect confirmations: {len(auto['false_confirmations'])}. Unverified: {len(auto['unverified_confirmations'])}.</p>
<h2>Processing time</h2><p>Median {h(timing['median'])}s · P90 {h(timing['p90'])}s · P95 {h(timing['p95'])}s · Maximum {h(timing['maximum'])}s.</p>
<h2>Scope and limitations</h2><ul>{''.join('<li>'+h(x)+'</li>' for x in report['limitations'])}</ul><p>{h(report['criterion'])}</p>
<label>Show <select id="filter"><option value="all">All receipts</option><option value="failed">At least one incorrect or unscorable field</option><option value="auto">Automatically confirmed</option><option value="false-auto">Incorrect / unscorable auto-confirmations</option></select></label>
<div class="table"><table><thead><tr><th>Original image</th><th>Merchant</th><th>Date</th><th>Total</th><th>Decision</th><th>Elapsed</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<h2>Reproducibility</h2><p>Manifest SHA-256: <code>{report['manifest_sha256']}</code></p><p>Reference SHA-256: <code>{report['reference_sha256']}</code></p>
<script>document.getElementById('filter').onchange=e=>document.querySelectorAll('tbody tr').forEach(r=>{{const v=e.target.value;r.hidden=v==='failed'&&r.dataset.failed!=='true'||v==='auto'&&r.dataset.auto!=='true'||v==='false-auto'&&!(r.dataset.failed==='true'&&r.dataset.auto==='true')}});</script></main></html>'''
    output = ROOT / 'output/quality/blind100.html'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--allow-partial', action='store_true')
    score(parser.parse_args().allow_partial)
