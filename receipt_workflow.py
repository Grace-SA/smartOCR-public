"""Editable workflow metadata around the frozen extraction, with an audit trail."""
from copy import deepcopy
from datetime import date
import math
import re

from receipt_confidence import apply_confidence, UNKNOWN_MERCHANTS
from receipt_engine import CATEGORIES, MERCHANTS, normalise_category, now


def organise_record(record):
    """Derive editable metadata without changing extracted financial facts."""
    evidence = record.setdefault('field_evidence', {})
    manual = evidence.get('category', {}).get('method') == 'user_review'
    merchant = record.get('merchant') or ''
    if not manual and normalise_category(record.get('category')) in ('Other', 'Uncategorised'):
        choices = [(pattern, category) for pattern, _, category in MERCHANTS]
        choices += [(r'\b(cafe|restaurant|espresso|bakery|catering)\b', 'Dining'),
                    (r'\b(taxi|cabcharge|parking|cabs?|bus hire)\b', 'Transport & fuel')]
        for pattern, category in choices:
            if re.search(pattern, merchant, re.I):
                record['category'] = category
                evidence['category'] = {'method':'merchant_rule', 'text':'Suggested from the recognised merchant type; editable at any time.'}
                break
    previous = set(record.get('automatic_tags', []))
    manual_tags = [tag for tag in record.get('tags', []) if tag not in previous]
    automatic = []
    if record.get('date'): automatic.append('Month: ' + record['date'][:7])
    category = normalise_category(record.get('category'))
    if category != 'Uncategorised': automatic.append(category)
    if isinstance(record.get('total'), (int, float)) and record['total'] < 0: automatic.append('Refund')
    if record.get('purpose') in ('work', 'personal'): automatic.append(record['purpose'].title())
    automatic = [tag for tag in automatic if tag not in record.get('suppressed_automatic_tags', [])]
    record['automatic_tags'] = automatic
    record['tags'] = list(dict.fromkeys(manual_tags + automatic))
    return record

CORE = {'merchant', 'date', 'total', 'currency'}
ALLOWED = CORE | {'category', 'purpose', 'status', 'tags', 'notes'}
BULK_ALLOWED = {'category', 'purpose', 'tags'}


def prepare_record(record):
    record.setdefault('original_extraction', {k: deepcopy(record.get(k)) for k in CORE})
    record['category'] = normalise_category(record.get('category'))
    organise_record(record)
    apply_confidence(record)
    record['workflow_warnings'] = record['confidence']['reasons']
    return record


def validate_changes(changes, bulk=False):
    if not isinstance(changes, dict) or not changes or set(changes) - (BULK_ALLOWED if bulk else ALLOWED):
        raise ValueError('Unsupported or empty changes')
    changes = deepcopy(changes)
    for key in ('merchant', 'date', 'currency', 'category', 'purpose', 'status', 'notes'):
        if key == 'date' and changes.get(key) is None:
            continue
        if key in changes and not isinstance(changes[key], str):
            raise ValueError(key.title() + ' must be text')
    if 'merchant' in changes:
        changes['merchant'] = changes['merchant'].strip()
    if changes.get('date'):
        if date.fromisoformat(changes['date']).isoformat() != changes['date']:
            raise ValueError('Use an ISO date (YYYY-MM-DD)')
    if 'total' in changes and changes['total'] is not None:
        value = changes['total']
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > 1e8:
            raise ValueError('Invalid amount')
        changes['total'] = round(value, 2)
    for key, options in [('purpose', {'unknown', 'personal', 'work'}), ('status', {'review', 'confirmed'}),
                         ('currency', {'AUD', 'NZD', 'USD', 'EUR', 'GBP', 'CNY', 'UNKNOWN'}), ('category', CATEGORIES)]:
        if key in changes and changes[key] not in options:
            raise ValueError('Invalid ' + key)
    if 'tags' in changes:
        tags = changes['tags']
        if not isinstance(tags, list) or len(tags) > 20 or any(not isinstance(t, str) or len(t) > 40 for t in tags):
            raise ValueError('Use up to 20 tags, each up to 40 characters')
        changes['tags'] = list(dict.fromkeys(t.strip() for t in tags if t.strip()))
    if any(len(str(v)) > 2000 for v in changes.values()):
        raise ValueError('Field is too long')
    return changes


def complete_core(record):
    return (isinstance(record.get('merchant'), str)
            and record['merchant'].strip().casefold() not in UNKNOWN_MERCHANTS
            and bool(record.get('date')) and record.get('total') is not None)


def update_record(record, changes):
    """Return a copy so rejected updates never partially mutate the database."""
    changes = validate_changes(changes)
    result = prepare_record(deepcopy(record))
    before = {key: result.get(key) for key in changes}
    core_changed = any(key in changes and changes[key] != result.get(key) for key in CORE)
    previous_status = result.get('status')
    result.update(changes)
    if 'tags' in changes:
        removed = set(record.get('automatic_tags', [])) - set(changes['tags'])
        result['suppressed_automatic_tags'] = sorted((set(record.get('suppressed_automatic_tags', [])) | removed) - set(changes['tags']))
    if 'category' in changes:
        result.setdefault('field_evidence', {})['category'] = {'method':'user_review','text':changes['category']}
    at = now()
    if changes.get('status') == 'confirmed' and not complete_core(result):
        raise ValueError('Enter a merchant, date and total before confirming')
    if changes.get('status') == 'review':
        result['status'] = 'review'
        result['review_decision'] = {'mode': 'manual_reopen', 'at': at, 'reason': 'Reopened by the user'}
    elif core_changed:
        result['status'] = 'confirmed' if complete_core(result) else 'review'
        result['review_decision'] = {'mode': 'override', 'at': at, 'reason': 'Extraction corrected by the user'}
    elif changes.get('status') == 'confirmed':
        result['review_decision'] = {'mode': 'human_confirmed', 'at': at, 'reason': 'Checked by the user'}
    result['updated_at'] = at
    if previous_status != result.get('status'):
        before.setdefault('status', previous_status)
    after = {key: result.get(key) for key in before}
    result.setdefault('edit_history', []).append({'at': at, 'before': before, 'after': after, 'actor': 'user'})
    for key, value in changes.items():
        result.setdefault('field_evidence', {})[key] = {'method': 'user_review', 'text': str(value)}
    return prepare_record(result)
