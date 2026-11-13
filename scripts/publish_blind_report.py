"""Add interpretation to a completed blind report without changing its scores.

Inputs are the frozen evaluator's final JSON/HTML, a hash-bound final diagnosis,
the original manifest, and the already generated workbook. No OCR is performed.
"""
import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
START = '<!-- blind100-interpretation:start -->'
END = '<!-- blind100-interpretation:end -->'
ANCHOR = '<div class="cards">'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def href(path, parent):
    return quote(os.path.relpath(path, parent).replace(os.sep, '/'), safe='/.-_')


def write_if_changed(path, data):
    if path.exists() and path.read_bytes() == data:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.publishing.tmp')
    temporary.write_bytes(data)
    temporary.replace(path)


def publish(evaluation, diagnosis, manifest, workbook, primary, strict, sources, audit):
    paths = [Path(p).resolve() for p in
             (evaluation, diagnosis, manifest, workbook, primary, strict, sources, audit)]
    evaluation, diagnosis, manifest, workbook, primary, strict, sources, audit = paths
    require(len(set(paths)) == len(paths), 'Input and output paths must all be distinct.')
    eb, db, mb = (p.read_bytes() for p in (evaluation, diagnosis, manifest))
    ev, dg, mf = (json.loads(b) for b in (eb, db, mb))
    require(ev.get('complete') is True and ev.get('tested_count') == 100,
            'Publishing requires complete=true and tested_count=100.')
    require(ev.get('selected_count') == 100 and ev.get('target_count') == 100,
            'Publishing requires the selected final 100-receipt cohort.')
    rows = ev.get('results', [])
    ids = {r['id'] for r in rows}
    require(len(rows) == len(ids) == 100, 'Evaluation must have 100 unique receipt IDs.')
    require(dg.get('evaluation_source_sha256') == digest(eb),
            'Diagnosis must be bound to this exact final evaluation SHA-256.')
    require(set(dg.get('scope_ids', [])) == ids and len(dg.get('scope_ids', [])) == 100,
            'Final diagnosis must cover exactly the final 100 IDs.')
    require(len(dg.get('records', [])) == 100 and
            {r['id'] for r in dg['records']} == ids,
            'Final diagnosis must contain one record per final receipt.')
    require(dg.get('rules_references_predictions_unchanged') is True,
            'Diagnosis must attest that frozen evidence and rules are unchanged.')
    require(isinstance(mf, list) and len(mf) == 100 and {r['id'] for r in mf} == ids,
            'Manifest must contain exactly the evaluated cohort.')
    require(digest(mb) == ev.get('manifest_sha256'),
            'Manifest bytes must match the final evaluation hash.')
    require(all(isinstance(r.get('source'), dict) and r['source'].get('url') for r in mf),
            'Each source manifest entry must retain its original public URL.')
    require(workbook.is_file() and workbook.read_bytes()[:2] == b'PK',
            'Generate the final downloadable XLSX before publishing.')

    # Existing diagnostic schema: a finding holds the mutually exclusive groups.
    candidates = [x['groups'] for x in dg.get('important_findings', [])
                  if isinstance(x, dict) and isinstance(x.get('groups'), dict)]
    require(len(candidates) == 1, 'Diagnosis must provide exactly one merchant groups object.')
    groups = candidates[0]
    require(all(isinstance(v, list) for v in groups.values()), 'Merchant groups must be ID lists.')
    grouped = [rid for group in groups.values() for rid in group]
    merchant_nonmatches = {r['id'] for r in rows if r['field_matches']['merchant'] is False}
    require(len(grouped) == len(set(grouped)) and set(grouped) == merchant_nonmatches,
            'Diagnostic groups must partition the strict merchant mismatches exactly.')
    variants = groups.get('same_brand_or_full_legal_name_variants', [])
    auto_ids = set(ev['automatic'].get('false_confirmations', [])) | set(
        ev['automatic'].get('unverified_confirmations', []))
    adjudications = dg.get('visual_auto_adjudications', [])
    require(len(adjudications) == len(auto_ids) and
            {x['id'] for x in adjudications} == auto_ids,
            'Every strict auto-nonmatch must have a final visual diagnostic entry.')
    require(all(x.get('original_reopened') is True and x.get('strict_score_unchanged') is True
                and x.get('notes') for x in adjudications),
            'Automatic diagnostic entries need original-image review, unchanged scores and notes.')
    by_id = {r['id']: r for r in rows}
    faithful = [x['id'] for x in adjudications
                if x.get('actual_is_literal_printed_name') is True
                and x.get('same_merchant_entity_observed') is True
                and x.get('date_matches_original') is True
                and x.get('total_matches_original') is True]
    require(set(faithful) <= set(variants), 'Faithful auto examples must also occur in the variant group.')
    require(all(by_id[rid].get('auto_confirmed') is True and
                by_id[rid]['field_matches']['date'] is True and
                by_id[rid]['field_matches']['total'] is True for rid in faithful),
            'Faithful name-only examples must retain strict date/amount matches.')

    current = primary.read_bytes()
    previous = json.loads(audit.read_text()) if audit.exists() else None
    if START.encode() in current:
        require(previous is not None and strict.is_file(),
                'An interpreted page requires its existing original and publication audit.')
        require(digest(current) == previous.get('published_html_sha256'),
                'Published HTML changed externally; refusing to overwrite it.')
        original = strict.read_bytes()
    else:
        original = current
        if strict.exists():
            require(strict.read_bytes() == original, 'Existing strict report differs; it will not be overwritten.')
    require(START.encode() not in original and END.encode() not in original,
            'Original strict report must not already include publisher notes.')
    require(original.count(ANCHOR.encode()) == 1, 'Strict report has an unexpected HTML structure.')
    require(b'100 tested / 100 requested' in original and b'IN PROGRESS' not in original,
            'Original HTML must be the final 100-receipt strict report.')
    if previous:
        require(digest(original) == previous.get('original_html_sha256'),
                'Original strict HTML hash no longer matches its audit.')
        require(digest(eb) == previous.get('evaluation_sha256'),
                'Final evaluation changed after publication; refusing to replace its audit.')

    h = lambda value: escape(str(value), quote=True)
    id_list = lambda values: ', '.join(h(v) for v in values) or 'None'
    labels = {
        'nonidentifying_legal_suffix': 'Nonidentifying legal suffix only',
        'same_brand_or_full_legal_name_variants': 'Same printed brand or full legal-name variants',
        'missing_or_placeholder': 'Missing merchant or placeholder',
        'printed_outlet_descriptor': 'Printed outlet descriptor instead of brand',
        'address_locality': 'Address locality selected as merchant',
    }
    group_rows = ''.join(
        f'<tr><td>{h(labels.get(key, key.replace("_", " ")))}</td>'
        f'<td>{len(values)}</td><td>{id_list(values)}</td></tr>'
        for key, values in groups.items())
    auto_rows = ''.join(
        '<tr><td>' + h(x['id']) + '</td><td>' + h(by_id[x['id']]['expected']['merchant']) +
        '</td><td>' + h(by_id[x['id']]['actual']['merchant']) + '</td><td>' +
        h(x['notes']) + '</td></tr>' for x in adjudications)
    auto_details = (
        '<details><summary>Visual diagnosis for each strict auto-nonmatch</summary>'
        '<div class="table"><table><thead><tr><th>Receipt</th><th>Strict reference name</th>'
        '<th>Extracted name</th><th>Visual interpretation</th></tr></thead><tbody>' +
        auto_rows + '</tbody></table></div></details>' if auto_rows else '')
    note = f'''{START}
<section class="notice" aria-labelledby="interpretation-title">
<h2 id="interpretation-title">Interpretation note — strict matching and visual diagnosis</h2>
<p>The numeric results below are the unchanged frozen evaluator results. Strict merchant-name
matching can penalise a faithful full legal name or another brand form printed on the receipt.
A strict auto-nonmatch therefore does not automatically mean that the wrong business was identified.
Missing fields and incorrect dates or amounts remain failures.</p>
<p>The final visual diagnosis identifies <b>{len(variants)} same-brand or full legal-name variants</b>
among strict merchant mismatches: {id_list(variants)}.</p>
<p>Of the {len(auto_ids)} strict incorrect or unverified auto-confirmations, the diagnosis records
{len(faithful)} cases whose extracted merchant is the literal printed name of the same business
and whose date and total match the original: {id_list(faithful)}.
These are case observations, not a replacement accuracy or precision metric and not proof of future reliability.</p>
{auto_details}
<details><summary>Merchant mismatch diagnosis: exact counts and receipt IDs</summary>
<div class="table"><table><thead><tr><th>Diagnostic group</th><th>Count</th><th>Receipt IDs</th></tr></thead>
<tbody>{group_rows}</tbody></table></div></details>
<ul><li>73% of this cohort consists of transport receipts. Results should not be generalised to all Australian retail receipts.</li>
<li>References are assistant visual transcriptions with second-assistant review, not independent human gold.</li>
<li>Five previously used transactions were excluded and replaced before their OCR predictions were inspected;
selection was not changed in response to OCR failures. Excluded IDs: blind_063, blind_064,
blind_065, blind_066 and blind_067. None counts toward the final 100.</li>
<li>Original-image provenance is preserved in the verbatim source manifest, including public source URLs,
PDF page/crop metadata where applicable, and image hashes.</li></ul>
<p><a href="{h(href(strict, primary.parent))}">Unmodified strict report</a> ·
<a href="{h(href(workbook, primary.parent))}" download>Download final Excel workbook</a> ·
<a href="{h(href(sources, primary.parent))}" download>Download original source manifest</a></p>
</section>
{END}
'''
    published = original.replace(ANCHOR.encode(), note.encode() + ANCHOR.encode(), 1)
    published = published.replace(b"querySelectorAll('tbody tr')", b"querySelectorAll('tr[data-failed]')")
    record = {
        'schema_version': 1,
        'first_published_at': previous['first_published_at'] if previous else datetime.now(timezone.utc).isoformat(),
        'publisher_source': str(Path(__file__).resolve()),
        'publisher_sha256': digest(Path(__file__).read_bytes()),
        'evaluation_path': str(evaluation), 'evaluation_sha256': digest(eb),
        'diagnosis_path': str(diagnosis), 'diagnosis_sha256': digest(db),
        'original_html_path': str(strict), 'original_html_sha256': digest(original),
        'published_html_path': str(primary), 'published_html_sha256': digest(published),
        'manifest_path': str(manifest), 'source_copy_path': str(sources),
        'source_manifest_sha256': digest(mb),
        'workbook_path': str(workbook), 'workbook_sha256': digest(workbook.read_bytes()),
        'interpretation_note_sha256': digest(note.encode()),
        'strict_scores_unchanged': True, 'semantic_metric_computed': False,
        'same_brand_or_full_legal_name_variant_ids': variants,
        'strict_auto_nonmatch_ids': sorted(auto_ids),
        'visually_faithful_auto_name_with_matching_date_total_ids': faithful,
        'merchant_diagnostic_counts': {key: len(values) for key, values in groups.items()},
    }
    # All validation is complete before any output is written. Original bytes
    # and the manifest are copied verbatim; reruns leave identical files intact.
    write_if_changed(strict, original)
    write_if_changed(sources, mb)
    write_if_changed(primary, published)
    write_if_changed(audit, (json.dumps(record, indent=2) + '\n').encode())
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    defaults = {
        'evaluation': 'research/blind100/evaluation.json',
        'diagnosis': 'research/blind100/diagnosis_final100.json',
        'manifest': 'research/blind100/manifest.json',
        'workbook': 'output/exports/blind100-evaluation.xlsx',
        'primary': 'output/quality/blind100.html',
        'strict': 'output/quality/blind100-strict.html',
        'sources': 'output/quality/blind100-sources.json',
        'audit': 'output/quality/blind100-publication-audit.json',
    }
    for name, default in defaults.items():
        parser.add_argument('--' + name, type=Path, default=ROOT / default)
    result = publish(**vars(parser.parse_args()))
    print(json.dumps({key: result[key] for key in
                      ('published_html_path', 'original_html_sha256', 'published_html_sha256',
                       'source_manifest_sha256')}, indent=2))


if __name__ == '__main__':
    main()
