"""Strict arithmetic evidence for a complete, counted item subtotal.

This module never extracts or invents a receipt's final total. Its result may
only corroborate an independently printed TOTAL candidate. It reads no files,
sample identifiers, merchant registry, or reference annotations.
"""
from __future__ import annotations

import re
from decimal import Decimal


_NUMBER = r'(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}'
_AMOUNT = rf'(?:-\s*)?(?:AUD\s*)?\$?\s*{_NUMBER}'
_MONEY = re.compile(rf'(?<![\w.,]){_AMOUNT}(?![\w.,])', re.I)
_SUBTOTAL = re.compile(
    rf'^(?P<count>\d{{1,3}})\s+SUB\s*TOTAL\s*:?\s*'
    rf'(?P<amount>(?:AUD\s*)?\$?\s*{_NUMBER})\s*$', re.I)
_QUANTITY = re.compile(
    rf'^(?:QTY|QUANTITY)\s*:?\s*(?P<count>\d{{1,3}})\s*@\s*'
    rf'(?P<unit>(?:AUD\s*)?\$?\s*{_NUMBER})\s*(?:EA\.?|EACH)'
    rf'(?:\s+(?P<extended>(?:AUD\s*)?\$?\s*{_NUMBER}))?\s*$', re.I)
_DISCOUNT = re.compile(r'\b(?:discount|disct|offer|promo|promotion)\b', re.I)
_NON_ITEM = re.compile(
    r'\b(?:total|subtotal|gst|tax|abn|invoice|receipt|phone|tel|fax|'
    r'payment|eft|eftpos|purchase|sale|balance|change|cash|tendered|'
    r'refund|returned|redemption|savings?|rewards?|points|minimum|spend|'
    r'served|manager|store|description|quantity|qty|unit\s*price|'
    r'delivery|freight|postage|surcharge|rounding|fee|gratuity)\b', re.I)
_ADJUSTMENT = re.compile(
    r'\bcash\s*out\b|\bsurcharge\b|\brounding\b|'
    r'\b(?:service|delivery)\s*(?:fee|charge)\b|\bfreight\b|'
    r'\bpostage\b|\bgratuity\b|\btip\b|'
    r'\b(?:tax|gst)\s*(?:added|extra|exclusive|excluded)\b', re.I)
_UNCERTAIN = re.compile(r'\[.*?(?:unreadable|illegible|unknown|unclear).*?\]|[?\ufffd]', re.I)


def _decimal(quote):
    return Decimal(re.sub(r'AUD|\$|,|\s', '', quote, flags=re.I))


def _description(text):
    """Accept a product description, not an accounting label or loose number."""
    return (len(re.findall(r'[A-Za-z]', text)) >= 3
            and not _NON_ITEM.search(text) and not _DISCOUNT.search(text)
            and not _UNCERTAIN.search(text) and not _MONEY.search(text)
            and not re.search(r'@|\b\d+\s*(?:for|x)\b', text, re.I))


def collect_counted_subtotal_check(rows, engine, variant):
    """Return complete-item arithmetic evidence or ``None`` on any ambiguity.

    Supported item grammar is deliberately narrow: a named item and its price;
    a description followed by ``Qty N @ unit ea extended``; or a priced item
    followed immediately by ``Qty N @ unit ea``. A single negative adjustment
    must explicitly say OFFER, DISCOUNT, DISCT, PROMO or PROMOTION. The one
    counted subtotal must equal both the exact item count and the cent sum.

    Unknown lines inside the item table, missing amounts, unsupported quantity
    notations, incomplete/duplicate subtotals, cash-out and subsequent fees or
    discounts reject the check. Conditional surcharge text is also rejected
    conservatively; this function does not infer whether a fee was charged.
    """
    if not isinstance(rows, (list, tuple)) or any(not isinstance(r, str) for r in rows):
        return None
    rows = [r.strip() for r in rows if r.strip()]
    if not rows or any('\n' in r for r in rows):
        return None
    subtotal_rows = [i for i, row in enumerate(rows) if re.search(r'\bSUB\s*TOTAL\b', row, re.I)]
    if len(subtotal_rows) != 1:
        return None
    end = subtotal_rows[0]
    subtotal = _SUBTOTAL.fullmatch(rows[end])
    if not subtotal:
        return None
    expected_count = int(subtotal['count'])
    expected_amount = _decimal(subtotal['amount'])
    if expected_count < 1 or expected_amount < 0:
        return None
    # A changed final charge invalidates using a merchandise subtotal as a
    # corroborating total, even if the counted merchandise is internally sound.
    if any(_ADJUSTMENT.search(row) for row in rows):
        return None
    if any(_DISCOUNT.search(row) and _MONEY.search(row) for row in rows[end+1:]):
        return None
    start = next((i for i, row in enumerate(rows[:end]) if _MONEY.search(row)), None)
    if start is None:
        return None
    # The first priced row itself can be a quantity extension, in which case
    # exactly one immediately preceding product description is required.
    if _QUANTITY.fullmatch(rows[start]):
        if start == 0 or not _description(rows[start-1]):
            return None
        start -= 1
    items, discounts, pending, excluded_units = [], [], None, []
    previous_kind = None
    for index in range(start, end):
        row = rows[index]
        if _UNCERTAIN.search(row):
            return None
        quantity = _QUANTITY.fullmatch(row)
        if quantity:
            count, unit = int(quantity['count']), _decimal(quantity['unit'])
            if count < 1 or unit < 0:
                return None
            extension = unit * count
            if quantity['extended']:
                if pending is None or extension != _decimal(quantity['extended']):
                    return None
                items.append({'description': pending['text'], 'quantity': count,
                              'unit_price': float(unit), 'value': float(extension),
                              'evidence': pending['text']+'\n'+row,
                              'quantity_evidence': row, 'line_index': pending['index']})
                pending = None
            else:
                if pending is not None or previous_kind != 'item' or not items or items[-1].get('quantity_evidence'):
                    return None
                if extension != Decimal(str(items[-1]['value'])):
                    return None
                items[-1].update({'quantity': count, 'unit_price': float(unit), 'quantity_evidence': row})
                items[-1]['evidence'] += '\n'+row
            excluded_units.append({'evidence': row, 'reason': 'unit_price_is_not_an_extra_charge'})
            previous_kind = 'quantity'
            continue
        amounts = list(_MONEY.finditer(row))
        if not amounts:
            if pending is not None or not _description(row):
                return None
            pending = {'text': row, 'index': index}
            previous_kind = 'description'
            continue
        # Every amount row must end in one unambiguous monetary value.
        if len(amounts) != 1 or row[amounts[0].end():].strip() or pending is not None:
            return None
        match = amounts[0]
        label = row[:match.start()].strip()
        amount = _decimal(match.group())
        if _DISCOUNT.search(label):
            if not items or amount >= 0 or not match.group().lstrip().startswith('-') or len(re.findall(r'[A-Za-z]', label)) < 3:
                return None
            discounts.append({'value': float(amount), 'evidence': row, 'line_index': index})
            previous_kind = 'discount'
            continue
        if amount < 0 or not _description(label):
            return None
        # An unqualified trailing count larger than one could be either a
        # quantity or part of the SKU/name. Require explicit Qty notation.
        trailing_count = re.search(r'\s(\d+)\s*$', label)
        if trailing_count and int(trailing_count[1]) > 1:
            return None
        items.append({'description': label, 'quantity': 1, 'value': float(amount),
                      'evidence': row, 'line_index': index})
        previous_kind = 'item'
    if pending is not None or not items:
        return None
    actual_count = sum(item['quantity'] for item in items)
    actual_amount = sum((Decimal(str(item['value'])) for item in items+discounts), Decimal('0.00'))
    if actual_count != expected_count or actual_amount != expected_amount:
        return None
    return {'kind': 'complete_item_sum', 'engine': engine, 'source_variant': variant,
            'value': float(actual_amount), 'item_count': actual_count,
            'priced_row_count': len(items), 'items': items, 'discounts': discounts,
            'header_evidence': '\n'.join(rows[:start]), 'count_evidence': rows[end],
            'subtotal_evidence': rows[end], 'printed_subtotal': float(expected_amount),
            'item_start_index': start, 'subtotal_index': end,
            'excluded_unit_price_rows': excluded_units,
            'scope': 'supports_existing_printed_total_only'}
