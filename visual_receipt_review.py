"""Reconcile independent visual suggestions with retained OCR evidence.

This does not certify the model's interpretation. Changed fields always require
review; human corrections are immutable here. No references or IDs are answers.
"""
from copy import deepcopy
from decimal import Decimal
import re

from receipt_extraction_v2 import _plain_text, collect_candidates, MERCHANTS
from receipt_confidence import assess_confidence


def literal_name(value):
    return re.sub(r'[^a-z0-9]','',str(value).casefold().replace('&','and'))


def key(field,value):
    if value is None: return None
    if field=='merchant':
        text=str(value)
        # Registry typography/branch variants are not independent disagreements.
        # Match text aliases only; numeric ABN fallback is not a trading brand.
        for pattern,name in MERCHANTS:
            aliases=[part for part in pattern.split('|') if not re.search(r'[0-9]{2,}',part)]
            if aliases and re.search('|'.join(aliases),text,re.I): text=name;break
        return literal_name(text)
    if field=='total': return round(float(value),2)
    return value


def sources(record):
    for engine,details in record.get('ocr_engines',{}).items():
        for variant in details.get('variants',[]):
            if variant.get('quality',{}).get('recognition_complete'):
                yield engine,_plain_text(variant.get('evidence_text',''))


def summary_equations_support(text,value,visual_quote):
    """Verify an existing visual reading with two explicit summary equations.

    This never creates a total. A printed gross label must exist in OCR and
    the visual quote; item addition alone is insufficient. Still review-only.
    """
    gross=r'total\s+incl(?:usive|uding)?\s+(?:of\s+)?(?:g\.?\s*s\.?\s*t\.?|tax)'
    number=r'\$?\s*(\d[\d,]*(?:\.\d{2})?)'
    if not re.search(gross,text,re.I) or not re.search(gross,visual_quote or '',re.I): return False
    target=Decimal(str(value)).quantize(Decimal('.01'))
    def amounts(pattern,source=text):
        return {Decimal(m.replace(',','')).quantize(Decimal('.01')) for m in re.findall(pattern,source,re.I|re.M)}
    quoted=amounts(gross+r'\s*[:=]?\s*'+number,visual_quote)
    if target not in quoted: return False
    net=amounts(r'^\s*total\s*[:=]\s*'+number+r'\s*$')
    tax=amounts(r'^\s*(?:pl[ua]s\s*)?g\.?\s*s\.?\s*t\.?\s*[:=]\s*'+number+r'\s*$')
    deposits=amounts(number+r'\s*deposits?\b')
    remaining=amounts(number+r'\s*remain(?:ing)?\b')
    return any(n+t==target for n in net for t in tax) and any(d+r==target for d in deposits for r in remaining)


def supporting_sources(record,field,value,visual_quote=None):
    supporting=[]
    for engine,text in sources(record):
        if field=='merchant':
            header=[]
            for line in text.splitlines()[:20]:
                if re.match(r'^\s*(?:bill\s*to|ship\s*to|sold\s*to|customer|recipient|to)\s*:',line,re.I): break
                header.append(line)
            candidates=collect_candidates(text,engine)['merchant']
            # A supplier's explicitly labelled remittance legal name can
            # corroborate a trading name read from the logo. It is not itself
            # authority to automatically substitute a payee for a merchant.
            rows=text.splitlines(); remittance=[]
            for i,row in enumerate(rows):
                if re.search(r'\b(?:direct\s+deposit|account\s+name|bank\s+details)\b',row,re.I):
                    remittance.extend(r for r in rows[i:i+3] if re.search(r'\bpty\s+ltd\b',r,re.I))
            supported=bool(literal_name(value)) and (literal_name(value) in literal_name('\n'.join(header))
                        or any(literal_name(value)==literal_name(c['value']) for c in candidates)
                        or any(literal_name(value) in literal_name(r) for r in remittance))
        elif field=='date':
            supported=any(c['value']==value and c['score']>=82 and 'non_transaction_date_context' not in c['flags']
                          for c in collect_candidates(text,engine)['date'])
        else:
            # Literal presence is insufficient: a subtotal or labour charge can
            # appear correctly in both models while having the wrong role.
            supported=any(key(field,m['value'])==key(field,value) for m in collect_candidates(text,engine)['total'])
            if not supported: supported=summary_equations_support(text,value,visual_quote)
        if supported: supporting.append(engine)
    return sorted(set(supporting))


def apply_visual_review(record,visual):
    result=deepcopy(record)
    if result.get('status')=='confirmed' or result.get('review_decision',{}).get('mode') in ('override','human_confirmed','manual_reopen'):
        result['visual_review']={'state':'not_applied','reason':'User decision preserved'}
        return result
    if visual.get('state')!='complete':
        result['visual_review']={'state':'unavailable','reason':visual.get('error','Visual output incomplete')}
        return result
    suggestion=visual['record']
    if suggestion.get('source',{}).get('local_path')!=result.get('source',{}).get('local_path'):
        raise ValueError('Visual output does not belong to this source image')
    if suggestion.get('sha256') and result.get('sha256')!=suggestion['sha256']:
        raise ValueError('Visual output source image hash differs')
    audit={};changed=[]
    for field in ('merchant','date','total'):
        current=result.get(field);value=suggestion.get(field)
        if key(field,current)==key(field,value):
            audit[field]={'state':'agreement','value':value};continue
        quote=suggestion.get('visual_evidence',{}).get(field)
        support=supporting_sources(result,field,value,quote) if value is not None else []
        audit[field]={'state':'conflict','ocr_value':current,'visual_value':value,
                      'visual_quote':quote,'grounded_ocr_support':support,
                      'warning':'Evidence agreement does not prove correctness; changed fields require review.'}
        # Retain unsupported values as suggestions, not silent replacements.
        decision=result.get('reconciliation',{}).get('fields',{}).get(field,{})
        established_name=field=='merchant' and decision.get('status')=='accepted' and len(decision.get('engines',[]))>=2
        if value is not None and support and not established_name:
            result[field]=value;changed.append(field);audit[field]['state']='adopted_for_review'
            result.setdefault('reconciliation',{}).setdefault('fields',{})[field]={
                'value':value,'status':'review','score':70,'disagreement':True,
                'engines':support+['qwen3_vl'], 'evidence':[],
                'flags':['visual_semantic_selection_requires_review']}
            result.setdefault('field_evidence',{})[field]={'method':'visual_ai_with_ocr_support',
                'text':audit[field]['visual_quote'],'supporting_models':support,'automatic_confirmation':False}
    result['visual_review']={'state':'complete','fields':audit,'changed_fields':changed,
                             'engine':'Qwen3-VL','scope':'Independent image interpretation with literal OCR support'}
    if any(v['state']!='agreement' for v in audit.values()):
        result['status']='review'
        result['review_decision']={'mode':'needs_review','reason':'Visual interpretation and OCR disagree'}
        # Even a retained baseline reading cannot auto-confirm across a visual conflict.
        for field,v in audit.items():
            if v['state']!='agreement':
                result.setdefault('reconciliation',{}).setdefault('fields',{}).setdefault(field,{})['disagreement']=True
    result['confidence']=assess_confidence(result)
    if result.get('status')=='auto_confirmed' and not result['confidence']['auto_confirmable']:
        result['status']='review'
        result['review_decision']={'mode':'needs_review','reason':'Current evidence policy requires review'}
    return result
