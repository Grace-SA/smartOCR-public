"""Evidence-based triage; the index is deliberately not a probability.

This module never corrects extracted facts and never reads benchmark answers.
The fixed policy is evaluated alongside the frozen OCR in the new blind set.
"""
from __future__ import annotations

from datetime import date,datetime,timezone
from decimal import Decimal,InvalidOperation
import math
import re

POLICY_VERSION='evidence-v2-2026-11-13'
CORE_FIELDS=('merchant','date','total')
UNSAFE_FLAGS={'ambiguous_extra_decimal_digit','missing_decimal_separator','shared_legal_entity_abn',
              'generic_or_single_word_header','additional_adjustment_after_total'}
UNKNOWN_MERCHANTS={'','unknown','unrecognised merchant','unrecognized merchant','待识别商家','待确认'}


def _key(field,value):
    if value is None:return None
    if field=='merchant':return re.sub(r'[^a-z0-9]','',str(value).casefold().replace('&','and'))
    if field=='total':
        try:return str(Decimal(str(value)).quantize(Decimal('.01')))
        except (InvalidOperation,ValueError):return None
    return str(value)


def _valid(field,value):
    if field=='merchant':return isinstance(value,str) and value.strip().casefold() not in UNKNOWN_MERCHANTS and not re.fullmatch(r'\s*(?:pty\s*)?ltd\s*',value,re.I)
    if field=='date':
        try:return isinstance(value,str) and date.fromisoformat(value)<=date.today()
        except ValueError:return False
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def assess_confidence(record):
    """Compute triage from actual supporting quotes, without altering a value."""
    decisions=record.get('reconciliation',{}).get('fields',{})
    engines=record.get('ocr_engines',{})
    all_engines=all(engines.get(e,{}).get('recognition_complete') for e in ('paddle','unlimited','oxr'))
    fields={};reasons=[]
    for field in CORE_FIELDS:
        decision=decisions.get(field,{})
        value=record.get(field)
        valid=_valid(field,value)
        matching=_key(field,value)==_key(field,decision.get('value'))
        votes={str(c.get('engine','')).split(':')[0] for c in decision.get('evidence',[])
               if _key(field,c.get('value'))==_key(field,value)
               and 'source_output_capped' not in c.get('flags',[])
               and c.get('score',0)>=82}
        votes={e for e in votes if engines.get(e,{}).get('recognition_complete')}
        # Three complete, uncapped readings of the same anchored business
        # header can corroborate an unfamiliar name. Never count crops twice.
        if field == 'merchant':
            header_votes = {str(c.get('engine','')).split(':')[0] for c in decision.get('evidence', [])
                            if _key(field,c.get('value')) == _key(field,value)
                            and c.get('score',0) >= 78
                            and 'business_header_context' in c.get('flags', [])
                            and not (set(c.get('flags', [])) & (UNSAFE_FLAGS | {'source_output_capped'}))}
            if all_engines and {'paddle','unlimited','oxr'} <= header_votes:
                votes.update(header_votes)
        flags=set(decision.get('flags',[]))
        flags.update(f for c in decision.get('evidence',[]) for f in c.get('flags',[]))
        problems=[]
        if not valid:problems.append('Missing or invalid '+field)
        if not matching:problems.append('Current value differs from the extraction')
        if decision.get('status')!='accepted':problems.append('The extractor did not accept a value')
        if decision.get('disagreement'):problems.append('The OCR evidence contains competing values')
        if len(votes)<2:problems.append('Fewer than two independent models support this value')
        if flags&UNSAFE_FLAGS:problems.append('The receipt contains ambiguous amount or identity evidence')
        if not all_engines:problems.append('One or more OCR models have incomplete output')
        score=99 if len(votes)>=3 else 95 if len(votes)==2 else 72 if votes else 30
        if decision.get('disagreement'):score=min(score,84)
        if flags&UNSAFE_FLAGS:score=min(score,79)
        if not all_engines:score=min(score,79)
        if not matching or decision.get('status')!='accepted':score=min(score,49)
        if not valid:score=0
        fields[field]={'score':score,'independent_models':sorted(votes),'ready':not problems,'reasons':problems}
        reasons.extend(field.title()+': '+p for p in problems)
    overall=min((f['score'] for f in fields.values()),default=0)
    ready=all(f['ready'] for f in fields.values())
    return {'score':overall,'band':'high' if ready else 'medium' if overall>=70 else 'low',
            'auto_confirmable':ready,'fields':fields,'reasons':list(dict.fromkeys(reasons)),
            'policy_version':POLICY_VERSION,'calibrated':False,'scope':list(CORE_FIELDS),
            'label':'Extraction confidence index',
            'explanation':'Evidence strength, not a probability or a guarantee. Auto-confirmation covers merchant, date and total; purpose and category remain editable.'}


def apply_confidence(record,preserve_user=True):
    """Mark safe extractions ready, preserve explicit human decisions/overrides."""
    result=assess_confidence(record)
    record['confidence']=result
    manual=record.get('review_decision',{}).get('mode') in ('human_confirmed','manual_reopen','override')
    if preserve_user and (record.get('status')=='confirmed' or manual):return record
    record['status']='auto_confirmed' if result['auto_confirmable'] else 'review'
    record['review_decision']={'mode':'automatic' if result['auto_confirmable'] else 'needs_review',
                              'policy_version':POLICY_VERSION,'at':datetime.now(timezone.utc).isoformat(),
                              'reason':'Independent evidence agrees on all three core fields' if result['auto_confirmable'] else 'Review only the flagged fields'}
    return record
