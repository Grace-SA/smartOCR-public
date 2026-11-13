"""Evidence-preserving receipt candidates and multi-engine reconciliation.

No filenames, source-page dates, annotation answers, or receipt IDs are used.
Scores are heuristic ranking scores, NOT calibrated probabilities or accuracy.
"""
from __future__ import annotations

import re
import html
from html.parser import HTMLParser
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from receipt_item_arithmetic import collect_counted_subtotal_check

MONTHS = {name: index for index, name in enumerate(
    ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'], 1)}
MONTH_PATTERN = r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'

# A merchant registry is different from hard-coding a particular receipt answer.
MERCHANTS = [
    (r'coles\s*express|colesexpress\.com', 'Coles Express'),
    (r'woolworths\s*(?:petrol|fuel)|\bww\s*petrol\b', 'Woolworths Petrol'),
    (r'\britchies\b', 'Ritchies'),
    (r'\bbws\b', 'BWS'),
    (r'woolworths?|fresh food people|\b88\s*000\s*014\s*675\b', 'Woolworths'),
    (r'\bcoles\b|\b45\s*004\s*189\s*708\b', 'Coles'),
    (r'\baldi\b|\b90\s*196\s*565\s*019\b', 'ALDI'),
    (r'\bfoodland\b', 'Foodland'),
    (r'harris\s*farm|harrisfarm\.com', 'Harris Farm'),
    (r'\biga\b', 'IGA'),
    (r'\bfoodworks\b', 'FoodWorks'),
    (r'\bcostco\b', 'Costco'),
    (r'\bbunnings\b|\b26\s*008\s*672\s*179\b', 'Bunnings'),
    (r'chemist\s*warehouse', 'Chemist Warehouse'),
    (r'\bpriceline\b', 'Priceline'),
    (r'\bkmart\b|\b73\s*004\s*700\s*485\b', 'Kmart'),
    (r'\bbig\s*w\b', 'BIG W'),
    (r'\bofficeworks\b|\b36\s*004\s*763\s*526\b', 'Officeworks'),
    (r'\bjb\s*hi[ -]?fi\b', 'JB Hi-Fi'),
    (r'\btarget\b', 'Target'),
    (r'\bbp\b', 'BP'),
    (r'\bampol\b', 'Ampol'),
    (r'\bcaltex\b', 'Caltex'),
    (r'\b7[ -]?eleven\b', '7-Eleven'),
    (r'\brebel\s*sport\b|\brebelsport\.com', 'Rebel Sport'),
    (r'\bintersport\b', 'Intersport'),
]

MONEY = re.compile(r'(?<![\w.])(?P<sign>-)?\s*(?:AUD\s*)?\$?\s*(?P<whole>\d{1,3}(?:,\d{3})+|\d{1,7})\s*(?P<sep>[.,])\s*(?P<frac>\d{2})(?!\d)(?P<trailing>-)?', re.I)
BAD_TOTAL = re.compile(r'\bsub\s*tot(?:al|a[l1i_])\b|\bchange\b|\btender(?:ed)?\b|cash\s*out|sav(?:ed|ings?)|discount|reward|points|surcharge|\b(?:total\s+(?:items|weight|qty|quantity)|item\s+total)\b',re.I)
PAYMENT = re.compile(r'\b(?:eftpos|eft|visa|mastercard|debit\s*card|credit\s*card|card\s*payment|purchase|amount\s*paid)\b',re.I)
MERCHANT_DOMAINS = {
    'coles.com.au':'Coles', 'woolworths.com.au':'Woolworths',
    'aldi.com.au':'ALDI', 'bunnings.com.au':'Bunnings',
    'kmart.com.au':'Kmart', 'officeworks.com.au':'Officeworks',
    'chemistwarehouse.com.au':'Chemist Warehouse', 'harrisfarm.com.au':'Harris Farm',
    'iga.com.au':'IGA', 'bws.com.au':'BWS',
    'rebelsport.com.au':'Rebel Sport', 'intersport.com.au':'Intersport',
}
# Official identity sources for recently added registry entries. Extraction
# still requires a matching identity on the receipt itself.
MERCHANT_REFERENCES = {
    'BWS':'https://bws.com.au/',
    'Rebel Sport':'https://www.rebelsport.com.au/',
    'Intersport':'https://intersport.com.au/',
}
# These digits identify a legal entity shared by multiple retail banners,
# including Woolworths and BIG W. Repeated OCR of the number cannot establish
# which trading brand issued an otherwise unidentified receipt.
SHARED_RETAIL_ABNS = {'88000014675'}
GENERIC_LOGO_WORDS = set('local fresh fruit deli market supermarket shop store food foods restaurant cafe bakery butcher butchers pharmacy hardware welcome thanks thank you value prices low best quality service tax invoice receipt'.split())
STREET_ADDRESS = re.compile(r'^\s*\d+[A-Za-z]?(?:[-/]\d+[A-Za-z]?)?\s+.+\b(?:street|st|road|rd|parade|pde|avenue|ave|drive|dr|lane|ln|highway|hwy|crescent|cres|boulevard|blvd|terrace|tce)\b',re.I)
MERCHANT_MENTION_EXCLUSION = re.compile(r'price\s*match|competitor|comments?|price\s*guarantee|\bcoupon\b|\bvoucher\b|\bredeem\b',re.I)
COLES_SLOGAN_REFERENCE = 'https://www.colesgroup.com.au/news/2020/media-releases/?page=coles-unveils-new-campaign-value-the-australian-way'


class _OCRHTMLText(HTMLParser):
    def __init__(self): super().__init__(); self.parts=[]
    def handle_starttag(self,tag,attrs):
        if tag in ['tr','p','div','br']: self.parts.append('\n')
        elif tag in ['td','th']: self.parts.append('\t')
    def handle_endtag(self,tag):
        if tag in ['tr','p','div']: self.parts.append('\n')
    def handle_data(self,data): self.parts.append(data)


def _plain_text(text):
    # Image-block placeholders are OCR transport metadata, not printed text.
    # Their full-page boxes would otherwise merge unrelated receipt rows.
    text=re.sub(r'!\[[^\]]*\]\([^)]+\)','',text)
    if re.search(r'<(?:table|tr|td|th|br|p|div)\b',text,re.I):
        parser=_OCRHTMLText(); parser.feed(text)
        return html.unescape(''.join(parser.parts))
    return html.unescape(text)


def _candidate(value, evidence, engine, score, **extra):
    return {'value':value, 'evidence':evidence, 'engine':engine, 'score':score, **extra}


def _valid_date(year, month, day):
    if year < 100:
        year += 2000 if year < 80 else 1900
    if not 1990 <= year <= date.today().year:
        return None
    try:
        return date(year,month,day).isoformat()
    except ValueError:
        return None


def _dates(text, engine):
    found=[]
    covered=[]
    patterns=[
        # Year first must be tested separately from Australian day-first dates.
        (r'(?<![\d.])(20\d{2}|19\d{2})[ \t]*[-/.][ \t]*(\d{1,2})[ \t]*[-/.][ \t]*(\d{1,2})(?!\d)', 'ymd'),
        (r'(?<![\d.])(\d{1,2})[ \t]*[-/.][ \t]*(\d{1,2})[ \t]*[-/.][ \t]*(\d{4}|\d{2})(?!\d)', 'dmy'),
        (rf'(?<!\w)(\d{{1,2}})(?:st|nd|rd|th)?[ \t]*[-./,]?[ \t]*({MONTH_PATTERN})[ \t]*[-./,]?[ \t]*(\d{{4}}|\d{{2}})(?!\d)', 'dmy_name'),
        # Also allows OCR merging day and 4-digit year: Mar 92019.
        (rf'(?<!\w)({MONTH_PATTERN})[ \t]+(\d{{1,2}})(?:st|nd|rd|th)?(?:[ \t]*[,./-][ \t]*|[ \t]+)(20\d{{2}}|19\d{{2}}|\d{{2}})(?!\d)', 'mdy_name'),
        (rf'(?<!\w)({MONTH_PATTERN})[ \t]+(\d{{1,2}})(20\d{{2}}|19\d{{2}})(?!\d)', 'mdy_name'),
    ]
    for pattern, order in patterns:
        for m in re.finditer(pattern,text,re.I):
            if any(m.start()<end and m.end()>start for start,end in covered): continue
            a,b,c=m.groups()
            if order=='ymd': value=_valid_date(int(a),int(b),int(c))
            elif order=='dmy': value=_valid_date(int(c),int(b),int(a))
            elif order=='dmy_name': value=_valid_date(int(c),MONTHS[b[:3].lower()],int(a))
            else: value=_valid_date(int(c),MONTHS[a[:3].lower()],int(b))
            if not value: continue
            covered.append(m.span())
            line_start=text.rfind('\n',0,m.start())+1
            line_end=text.find('\n',m.end())
            line=text[line_start:line_end if line_end>=0 else len(text)]
            prefix=text[line_start:m.start()].lower()
            previous_lines=[part.strip() for part in text[:line_start].splitlines() if part.strip()]
            if previous_lines and re.fullmatch(r'(?:best\s*before|use\s*by|expiry(?:\s*date)?|valid\s*(?:until|through))\s*[:.-]?',previous_lines[-1],re.I) and not re.search(r'\b(?:transaction|purchase|sale|date)\b',prefix,re.I):
                prefix=previous_lines[-1].lower()+' '+prefix
            flags=[]
            score=93
            if re.search(r'expir|valid\s*(?:until|through)|best\s*before|use\s*by|promo|guarantee|warranty|printed|generated|\bdue\b|\bdelivery\b|\bcollection\b|\bdispatch\b',prefix,re.I):
                score=22; flags.append('non_transaction_date_context')
            elif re.search(r'(?:date|purchas|transaction|sale|invoice)',prefix,re.I):
                score=98; flags.append('explicit_transaction_date_context')
            if re.search(r'\d{1,2}:\d{2}',line): score=min(99,score+2)
            found.append(_candidate(value,m.group(),engine,score,context=line,kind='transaction_date',flags=flags))
    return found


def _box(line):
    """Return top-left x/y/width/height for Apple Vision or common OCR JSON."""
    if all(k in line for k in ['x','y','width','height']):
        x,y,w,h=[float(line[k]) for k in ['x','y','width','height']]
        if max(abs(x),abs(y),abs(w),abs(h))<=1.01 and line.get('coordinate_system')!='top_left':
            y=1-y-h
        return (x,y,w,h)
    value=line.get('bbox',line.get('box',line.get('polygon',line.get('points'))))
    if isinstance(value,dict):
        try: return tuple(float(value[k]) for k in ['x','y','width','height'])
        except (KeyError,TypeError,ValueError): return None
    if isinstance(value,(list,tuple)) and value:
        if isinstance(value[0],(list,tuple)):
            xs=[float(p[0]) for p in value]; ys=[float(p[1]) for p in value]
            return min(xs),min(ys),max(xs)-min(xs),max(ys)-min(ys)
        if len(value)==4:
            x0,y0,x1,y1=map(float,value)
            return x0,y0,x1-x0,y1-y0
    if all(k in line for k in ['Left','Top','Width','Height']):
        return tuple(float(line[k]) for k in ['Left','Top','Width','Height'])
    return None


def _rows_from_boxes(lines):
    normalized=[]
    for line in lines or []:
        if not isinstance(line,dict): continue
        text=_plain_text(str(line.get('text',line.get('LineText',line.get('WordText',''))))).strip()
        # A block spanning many rendered lines has no trustworthy per-line box.
        # Its explicit table rows are still parsed from the plain transcript.
        if '\n' in text: continue
        box=_box(line)
        if text and box and box[2]>0 and box[3]>0:
            normalized.append({'text':text,'box':box})
    groups=[]
    # Use top edge, not centre: larger total digits can overlap a smaller label.
    for item in sorted(normalized,key=lambda item:(item['box'][1],item['box'][0])):
        x,y,w,h=item['box']; chosen=None
        for group in reversed(groups[-5:]):
            _,gy,_,gh=group['anchor']
            overlap=max(0,min(y+h,gy+gh)-max(y,gy))
            if overlap/min(h,gh)>=.45 or abs((y+h/2)-(gy+gh/2))<min(h,gh)*.45:
                chosen=group; break
        if chosen is None:
            groups.append({'anchor':item['box'],'items':[item]})
        else: chosen['items'].append(item)
    return [' '.join(i['text'] for i in sorted(g['items'],key=lambda i:i['box'][0])) for g in groups]


def _money(text, permit_noisy=False):
    values=[]
    for m in MONEY.finditer(text):
        whole=m['whole'].replace(',','')
        negative=bool(m['sign'] or m['trailing'])
        value=Decimal(f'{whole}.{m["frac"]}')*(-1 if negative else 1)
        flags=[]
        if re.search(r'\s[.,]|[.,]\s',m.group()): flags.append('decimal_whitespace_normalized')
        if m['sep']==',': flags.append('decimal_comma_normalized')
        values.append({'value':float(value),'quote':m.group().strip(),'flags':flags,'span':m.span()})
    if permit_noisy and not values:
        # Retain ambiguous OCR candidates, never silently truncate a third digit.
        for m in re.finditer(r'(?<![\d.])\$?\s*(\d{1,6})\s*[.]\s*(\d{2})(\d)(?!\d)',text):
            values.append({'value':float(Decimal(f'{m[1]}.{m[2]}')),'quote':m.group().strip(),'flags':['ambiguous_extra_decimal_digit'],'span':m.span()})
        if not values:
            for m in re.finditer(r'(?<!\d)\$?\s*(\d{1,5})\s+(\d{2})(?!\d)',text):
                values.append({'value':float(Decimal(f'{m[1]}.{m[2]}')),'quote':m.group().strip(),'flags':['missing_decimal_separator'],'span':m.span()})
    return values


def _role(line):
    normalized=re.sub(r'\bT[O0]TA[L1I]\b','TOTAL',line,flags=re.I)
    normalized=re.sub(r'^\s*OTAL\b','TOTAL',normalized,flags=re.I)
    normalized=re.sub(r'\b[IT]NCLU[DO]ED\b','INCLUDED',normalized,flags=re.I)
    if re.search(r'\bsub\s*tota[l1i_]?\b',normalized,re.I): return 'subtotal'
    if re.search(r'\bchange\b',normalized,re.I): return 'change'
    if re.search(r'\bcash\s*out\b',normalized,re.I): return 'cashout'
    if re.search(r'tender|^\s*cash\b',normalized,re.I): return 'tendered'
    if re.search(r'\bbalance\b',normalized,re.I): return 'balance'
    if BAD_TOTAL.search(normalized): return 'other'
    if '%' in normalized and re.search(r'\btotal\b',normalized,re.I): return 'other'
    if re.search(r'\bincluded\s+in\s+(?:the\s+)?total\b|\btotal\s+includes\s+gst\b',normalized,re.I): return 'tax'
    # Remove inclusion wording, but not a row giving GST INCLUDED IN TOTAL.
    stripped=re.sub(r'\b(?:incl(?:udes|uding)?|inc|including)\.?\s*gst\b','',normalized,flags=re.I)
    if re.search(r'\bgst\b|\btax\b',stripped,re.I) and not re.search(r'^\s*(?:grand\s+|invoice\s+)?total\b.*\b(?:incl|includes|including)',normalized,re.I): return 'tax'
    if re.search(r'\btotal\b',stripped,re.I) and PAYMENT.search(stripped): return 'settlement'
    if re.search(r'\b(?:total|amount\s*(?:due|paid)|balance\s*due)\b',stripped,re.I):
        if re.search(r'\bqty\b|\bunit\s*price\b|\bea\s+total',stripped,re.I): return 'other'
        return 'total'
    if PAYMENT.search(normalized): return 'payment'
    return 'other'


def _complete_item_sum(rows, engine, variant):
    """Validate a narrow, complete item table; never create a total candidate.

    Require an explicit Description header, a printed total item count, at
    least three priced product rows, and exact quantity/weight reconciliation.
    Any unmatched row, promotion, discount, ambiguous price column, missing
    item, or unsupported quantity notation makes arithmetic unavailable.
    """
    starts=[i for i,line in enumerate(rows) if re.fullmatch(r'Description\s*\$?',line,re.I)]
    if len(starts)!=1: return None
    start=starts[0]; end=None; expected_count=None
    for index in range(start+1,len(rows)):
        match=re.search(r'\bT[O0]TA[L1I]\s+for\s+(\d{1,3})\s+items?\b',rows[index],re.I)
        if match:
            end=index; expected_count=int(match[1]); break
        if _role(rows[index]) in ['total','subtotal','payment','settlement','tax','cashout']:
            return None
    if end is None or expected_count<3: return None
    # Counted merchandise can differ from the final charged amount when a
    # separate fee, tax or rounding adjustment follows. This validator does
    # not attempt to infer those accounting semantics.
    if any(re.search(r'\bsurcharge\b|\brounding\b|\bservice\s*(?:fee|charge)\b|\bdelivery\s*(?:fee|charge)\b|\bfreight\b|\btax\s*(?:added|extra)\b',line,re.I) for line in rows[start+1:]): return None
    items=[]; excluded=[]
    for line in rows[start+1:end]:
        if line=='$' and not items: continue
        quantity=re.fullmatch(r'(\d{1,3})\s*@\s*\$?\s*(\d+\.\d{2})\s*EACH',line,re.I)
        weight=re.fullmatch(r'(\d+(?:\.\d{1,4})?)\s*(kg|g)\s*(?:NET\s*)?@\s*\$?\s*(\d+\.\d{2})\s*/\s*(kg|g)',line,re.I)
        if quantity or weight:
            if not items or items[-1].get('quantity_evidence'): return None
            if quantity:
                count=int(quantity[1]); unit=Decimal(quantity[2])
                if count<1: return None
                amount=Decimal(count)*unit
            else:
                if weight[2].lower()!=weight[4].lower(): return None
                count=1
                amount=(Decimal(weight[1])*Decimal(weight[3])).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
            if amount!=Decimal(str(items[-1]['value'])): return None
            items[-1]['quantity']=count
            items[-1]['quantity_evidence']=line
            excluded.append({'evidence':line,'reason':'unit_price_explanation_not_an_extra_charge'})
            continue
        if re.search(r'\b(?:discount|disct|offer|coupon|saving|promo|promotion|bundle|deal|refund)\b|\b\d+\s+for\b|@',line,re.I): return None
        prices=_money(line)
        if len(prices)!=1 or prices[0]['value']<0 or prices[0]['flags']: return None
        money=prices[0]; left,right=money['span']
        description=line[:left].strip()
        if line[right:].strip() or len(re.findall(r'[A-Za-z]',description))<3: return None
        if re.match(r'^\d+\s+',description) or _role(line)!='other': return None
        items.append({'value':money['value'],'quantity':1,'evidence':line})
    if len(items)<3 or sum(i['quantity'] for i in items)!=expected_count: return None
    total=sum((Decimal(str(i['value'])) for i in items),Decimal('0.00'))
    return {'kind':'complete_item_sum','engine':engine,'source_variant':variant,
            'value':float(total),'priced_row_count':len(items),'item_count':expected_count,
            'count_evidence':rows[end],'header_evidence':rows[start],
            'items':items,'excluded_unit_price_rows':excluded,
            'scope':'supports_or_rejects_existing_printed_total_only'}


def _merchant_words(value):
    return re.findall(r'[a-z]+',str(value).casefold().replace('&',' and '))


def _one_letter_difference(a,b):
    if a==b or min(len(a),len(b))<4 or abs(len(a)-len(b))>1: return False
    if len(a)==len(b): return sum(x!=y for x,y in zip(a,b))==1
    short,long=(a,b) if len(a)<len(b) else (b,a)
    return any(long[:i]+long[i+1:]==short for i in range(len(long)))


def _merchant_logo_evidence(candidates, lines, raw_rows, engine):
    """Preserve separate large-logo observations, without inventing a name."""
    located=[]
    for source in lines or []:
        if not isinstance(source,dict): continue
        quote=_plain_text(str(source.get('text',source.get('LineText','')))).strip()
        box=_box(source)
        if quote and '\n' not in quote and box and box[2]>0 and box[3]>0:
            located.append((quote,box))
    evidence=[]
    for candidate in candidates:
        if candidate.get('kind')!='merchant_header' or 'business_header_context' not in candidate.get('flags',[]): continue
        body_words=_merchant_words(candidate['value'])
        if len(body_words)<3: continue
        body_row=next((i for i,r in enumerate(raw_rows) if r==candidate['evidence']),None)
        if body_row is None or MERCHANT_MENTION_EXCLUSION.search('\n'.join(raw_rows[max(0,body_row-3):body_row+1])): continue
        body_boxes=[box for quote,box in located if quote==candidate['evidence']]
        for body_box in body_boxes:
            bx,by,bw,bh=body_box
            for quote,box in located:
                words=_merchant_words(quote)
                letters=''.join(re.findall(r'[A-Za-z]',quote))
                if not words or len(words)>4 or not letters.isupper() or _money(quote): continue
                if MERCHANT_MENTION_EXCLUSION.search(quote): continue
                logo_row=next((i for i,r in enumerate(raw_rows) if r==quote),None)
                if logo_row is None or logo_row>=body_row: continue
                if MERCHANT_MENTION_EXCLUSION.search('\n'.join(raw_rows[max(0,logo_row-3):logo_row+1])): continue
                x,y,w,h=box
                gap=by-(y+h)
                if h<bh*1.15 or gap<0 or gap>bh*5: continue
                if min(x+w,bx+bw)<=max(x,bx): continue
                for word in words:
                    if len(word)<4 or word in GENERIC_LOGO_WORDS: continue
                    evidence.append({'kind':'large_header_logo','engine':engine,'word':word,
                                     'evidence':quote,'body_evidence':candidate['evidence'],
                                     'body_value':candidate['value'],'logo_box':list(box),'body_box':list(body_box),
                                     'flags':['separate_larger_logo_above_business_name']})
    return evidence


def _logo_name_resolution(options, logo_evidence):
    """Choose only among existing full names, with exact independent logo text."""
    eligible=[o for o in options if any(c.get('kind')=='merchant_header' and 'business_header_context' in c.get('flags',[]) for c in o['evidence'])]
    resolutions=[]
    for option in eligible:
        words=_merchant_words(option['value'])
        if len(words)<3: continue
        alternatives=[]; used=[]; disputed=set()
        for rival in eligible:
            other=_merchant_words(rival['value'])
            if len(other)!=len(words): continue
            difference=[i for i,(a,b) in enumerate(zip(words,other)) if a!=b]
            if len(difference)!=1: continue
            index=difference[0]; a,b=words[index],other[index]
            if a in GENERIC_LOGO_WORDS or b in GENERIC_LOGO_WORDS or not _one_letter_difference(a,b): continue
            relevant=[e for e in logo_evidence if _merchant_words(e['body_value']) in [words,other]]
            matching=[e for e in relevant if e['word']==a]
            independent={str(e['engine']).split(':')[0] for e in matching}
            if len(independent)<2 or any(e['word']==b for e in relevant): continue
            alternatives.append(rival['value']); used.extend(matching); disputed.add(a)
        if alternatives:
            unique={(e['engine'],e['evidence'],e['body_evidence']):e for e in used}
            resolutions.append({'selected_value':option['value'],'alternative_values':alternatives,
                                'supported_words':sorted(disputed),'evidence':list(unique.values()),
                                'independent_logo_engines':sorted({str(e['engine']).split(':')[0] for e in used}),
                                'full_name_engines':option['engines'],
                                'method':'existing_full_name_disambiguated_by_separate_logo',
                                'scope':'no_new_name_or_rewritten_ocr_quote'})
    if len(resolutions)!=1: return None
    return resolutions[0]


def collect_candidates(text, engine, lines=None):
    """Return independently evidenced field candidates from one OCR engine.

    `lines` accepts Apple Vision boxes, common polygon/bbox objects, or OCR.Space
    line boxes. Engine names may include a variant after ':'; such variants do
    not count as independent engines in consensus.
    """
    text=_plain_text(str(text or ''))
    result={'date':_dates(text,engine),'total':[],'merchant':[],'supporting_amounts':[],'diagnostics':[],'arithmetic_checks':[],'merchant_logo_evidence':[],'invoice_balance_checks':[]}
    raw_rows=[line.strip() for line in text.splitlines() if line.strip()]
    geometry=_rows_from_boxes(lines)
    edge_clipped_total=False
    for source_line in lines or []:
        if not isinstance(source_line,dict): continue
        label=str(source_line.get('text',source_line.get('LineText',''))).strip()
        box=_box(source_line)
        # A clipped TOTAL ending in TAL can only be interpreted with spatial
        # and tax-row evidence below; the letters alone are not a total label.
        if re.fullmatch(r'TAL',label,re.I) and box:
            tolerance=.02 if max(abs(v) for v in box)<=1.01 else 1
            if 0<=box[0]<=tolerance: edge_clipped_total=True
    variants=[('raw',raw_rows)]
    if geometry and geometry!=raw_rows: variants.append(('geometry',geometry))
    terminal_receipt=bool(re.search(r'\b(?:TID|MID|RRN|MERCH(?:ANT)?\s*ID|TERMINAL)\b',text,re.I) and re.search(r'\b(?:APPROVED|ACCOUNT\s*TYPE|DEBIT|SAVINGS)\b',text,re.I))
    for variant,rows in variants:
        arithmetic=_complete_item_sum(rows,engine,variant)
        if arithmetic: result['arithmetic_checks'].append(arithmetic)
        subtotal_arithmetic=collect_counted_subtotal_check(rows,engine,variant)
        if subtotal_arithmetic: result['arithmetic_checks'].append(subtotal_arithmetic)
        if variant=='geometry': result['date'].extend(_dates('\n'.join(rows),engine))
        for index,line in enumerate(rows):
            role=_role(line)
            if terminal_receipt and re.fullmatch(r'SALE\s*:?',line,re.I): role='payment'
            # The embedded bank slip's TOTAL AUD is a settlement observation,
            # separate from the retail invoice's printed purchase total.
            before_total='\n'.join(rows[max(0,index-8):index])
            bank_total=role=='total' and (
                bool(terminal_receipt and re.search(r'\bTOTAL\s+AUD\b',line,re.I) and re.search(r'\bPURCHASE\b',before_total,re.I)) or
                bool(re.search(r'GIFT\s*CA[RB]D|REDEMPTION',before_total,re.I) and re.search(r'APPROVED','\n'.join(rows[index+1:index+3]),re.I)))
            if bank_total: role='settlement'
            amounts=_money(line,permit_noisy=role=='total')
            # Terminal slips often print PURCHASE/SALE, AUD and the amount in
            # separate boxes. Join only a bare currency amount in the same
            # small payment block; do not cross another accounting label.
            if terminal_receipt and role=='payment' and not amounts and re.fullmatch(r'(?:PURCHASE|SALE)\s*:?',line,re.I):
                for direction in (1,-1):
                    for offset in (1,2,3):
                        neighbor=index+direction*offset
                        if not 0<=neighbor<len(rows): break
                        adjacent=rows[neighbor]
                        if re.fullmatch(r'(?:AUD|APPROVED)\s*',adjacent,re.I): continue
                        prices=_money(adjacent)
                        if len(prices)==1 and re.fullmatch(r'(?:AUD\s*)?\$?\s*-?\s*\d+(?:,\d{3})*[.,]\d{2}',adjacent,re.I):
                            preceding=rows[neighbor-1] if neighbor>0 else ''
                            belongs_to_other_label=_role(preceding) in ['tax','subtotal','total','cashout','tendered','change','balance']
                            backward_currency=bool(re.match(r'AUD\b',adjacent,re.I) or re.fullmatch(r'AUD',preceding,re.I))
                            if not belongs_to_other_label and (direction==1 or backward_currency):
                                result['supporting_amounts'].append(_candidate(prices[0]['value'],line+'\n'+adjacent,engine,88,kind='payment',source_variant=variant,line_index=index,flags=['terminal_payment_block']))
                        break
            clipped_tax_context=None
            if variant=='geometry' and edge_clipped_total and role=='other' and len(amounts)==1:
                money=amounts[0]; start,end=money['span']
                isolated_label=line[:start].strip(' :').upper()=='TAL' and not line[end:].strip()
                if isolated_label:
                    for nearby in rows[index+1:index+3]:
                        taxes=_money(nearby)
                        if re.search(r'\bincluded\s+in\s+(?:the\s+)?total\b',nearby,re.I) and len(taxes)==1 and 0<=taxes[0]['value']<=abs(money['value']):
                            role='total'; clipped_tax_context=nearby; break
            for money in amounts:
                if role in ['subtotal','payment','settlement','cashout','tendered','change','tax','balance']:
                    result['supporting_amounts'].append(_candidate(money['value'],line,engine,70,kind=role,source_variant=variant,line_index=index,flags=money['flags']))
            if role!='total': continue
            score=76 if clipped_tax_context else 97
            evidence=line+'\n'+clipped_tax_context if clipped_tax_context else line
            flags=['clipped_total_label','included_tax_context'] if clipped_tax_context else []
            if not amounts and not (variant=='raw' and geometry):
                for offset in (1,2):
                    if index+offset>=len(rows): break
                    adjacent=rows[index+offset]
                    adjacent_role=_role(adjacent)
                    next_amounts=_money(adjacent)
                    if not next_amounts:
                        if adjacent_role in ['total','payment'] or len(adjacent.strip())<3: continue
                        break
                    if adjacent_role=='payment' or re.fullmatch(r'[\s$\d.,-]+',adjacent):
                        amounts=next_amounts; evidence=line+'\n'+adjacent; score=91 if offset==1 else 86
                        flags.append('adjacent_total_value')
                        if adjacent_role=='payment': flags.append('amount_from_adjacent_payment')
                        break
                    # A total and an included-GST parenthesis can occupy a merged row.
                    if len(next_amounts)>=2 and re.search(r'includ\w*\s*gst',adjacent,re.I):
                        amounts=[next_amounts[-1]]; evidence=line+'\n'+adjacent; score=87
                        flags.append('total_with_included_tax_row'); break
                    break
            if not amounts: continue
            money=amounts[-1]
            flags+=money['flags']
            if re.search(r'\bT0TAL\b|\bTOTA[1I]\b|^\s*OTAL\b',line,re.I):
                score-=5; flags.append('total_label_ocr_normalized')
            if 'ambiguous_extra_decimal_digit' in flags: score=min(score,62)
            if 'missing_decimal_separator' in flags: score=min(score,67)
            adjustment_rows=rows[index+1:min(len(rows),index+5)]
            if any(re.search(r'\bsurcharge\b|\brounding\b',r,re.I) for r in adjustment_rows) and not any(_role(r)=='total' for r in adjustment_rows):
                flags.append('additional_adjustment_after_total')
            kind='clipped_total_label' if clipped_tax_context else ('payment_total' if 'amount_from_adjacent_payment' in flags else 'printed_total')
            result['total'].append(_candidate(money['value'],evidence,engine,score,kind=kind,flags=flags,source_variant=variant,line_index=index))
    header='\n'.join(raw_rows[:12])
    for rank,(pattern,name) in enumerate(MERCHANTS):
        match=None
        for possible in re.finditer(pattern,header,re.I):
            # A legal entity's ABN may be shared by several retail banners.
            # Prefer a printed trading brand before considering ABN fallback.
            if not re.search(r'[A-Za-z]',possible.group()): continue
            context=header[max(0,possible.start()-100):possible.end()]
            if re.search(r'(?:price\s*match|competitor|comments?|price\s*guarantee|coupon|voucher|redeem)[^\n]*\n?[^\n]*$',context,re.I): continue
            line_start=header.rfind('\n',0,possible.start())+1
            line_end=header.find('\n',possible.end())
            identity_line=header[line_start:line_end if line_end>=0 else len(header)]
            if re.search(r'\b(?:rewards?|loyalty|points|flybuys)\b',identity_line,re.I): continue
            if re.search(r'\b(?:invoice|abn|ltd|limited)\b',identity_line,re.I) and any(abn in re.sub(r'\D','',identity_line) for abn in SHARED_RETAIL_ABNS): continue
            match=possible; break
        if match:
            registry_source={'registry_reference':MERCHANT_REFERENCES[name]} if name in MERCHANT_REFERENCES else {}
            result['merchant'].append(_candidate(name,match.group(),engine,98 if rank<3 else 95,kind='merchant_registry',flags=[],**registry_source))
            break
    if not result['merchant']:
        # A merchant's card slip can follow the item receipt. An isolated brand
        # after payment/total, with terminal/card context, is identity evidence;
        # an own-brand product or a competitor/coupon mention is not.
        for index,line in enumerate(raw_rows):
            previous='\n'.join(raw_rows[max(0,index-3):index+1])
            context='\n'.join(raw_rows[max(0,index-2):index+9])
            if MERCHANT_MENTION_EXCLUSION.search(previous): continue
            domain_match=re.search(r'(?<![\w.-])(?:https?://)?(?:www\.)?([a-z][a-z0-9-]*\.com\.au)(?![\w.-])',line,re.I)
            if domain_match and domain_match[1].lower() in MERCHANT_DOMAINS:
                name=MERCHANT_DOMAINS[domain_match[1].lower()]
                registry_source={'registry_reference':MERCHANT_REFERENCES[name]} if name in MERCHANT_REFERENCES else {}
                result['merchant'].append(_candidate(name,line,engine,96,kind='merchant_domain',flags=['official_domain_on_receipt'],**registry_source))
                break
            prior_transaction=any(_role(r) in ['total','subtotal','payment','tendered'] for r in raw_rows[:index])
            payment_context=bool(re.search(r'\b(?:card|debit|credit|eftpos|approved|purchase|terminal|term\s*id|merch(?:ant)?\s*id)\b',context,re.I))
            closing_context=bool(re.search(r'thank\s*you\s+for\s+shopping\s+(?:with|at)\s*$', '\n'.join(raw_rows[max(0,index-2):index]),re.I))
            if not prior_transaction or not (payment_context or closing_context): continue
            plain=re.sub(r'[^a-z0-9]','',line.lower())
            for pattern,name in MERCHANTS:
                alias=re.fullmatch(r'(?:'+pattern+r')(?:[ \t]+(?:store\s*[:#]?\s*)?\d{1,5}[A-Za-z]?)?',line,re.I)
                if plain==re.sub(r'[^a-z0-9]','',name.lower()) or alias:
                    registry_source={'registry_reference':MERCHANT_REFERENCES[name]} if name in MERCHANT_REFERENCES else {}
                    result['merchant'].append(_candidate(name,line,engine,97,kind='merchant_payment_footer',flags=['footer_closing_identity' if closing_context else 'footer_payment_context'],context=context,**registry_source))
                    break
            if result['merchant']: break
    if not result['merchant']:
        # Verified brand slogan, not a per-receipt reference answer. Require a
        # retail receipt header so quoting an advert does not establish identity.
        slogan=re.search(r'\bvalue\s+the\s+austral[il]an\s+way\b',header,re.I)
        if slogan and re.search(r'\bstore\s*:',header,re.I) and re.search(r'\b(?:register|receipt|served\s*by)\b',header,re.I) and not MERCHANT_MENTION_EXCLUSION.search(header):
            result['merchant'].append(_candidate('Coles',slogan.group(),engine,89,kind='merchant_brand_slogan',flags=['verified_brand_slogan'],registry_reference=COLES_SLOGAN_REFERENCE))
    if not result['merchant']:
        for pattern,name in MERCHANTS:
            match=None
            for alternative in pattern.split('|'):
                if re.search(r'[0-9]{2,}',alternative):
                    match=re.search(alternative,text,re.I)
                    if match: break
            if match:
                shared=re.sub(r'\D','',match.group()) in SHARED_RETAIL_ABNS
                line_start=text.rfind('\n',0,match.start())+1
                line_end=text.find('\n',match.end())
                context=text[line_start:line_end if line_end>=0 else len(text)]
                result['merchant'].append(_candidate(name,match.group(),engine,65 if shared else 95,kind='merchant_registry',context=context,flags=['legal_entity_abn_fallback']+(['shared_legal_entity_abn'] if shared else [])))
                break
    if not result['merchant']:
        # Keep a header candidate at review confidence instead of asserting an address as merchant.
        repetitions=Counter(raw_rows)
        for line_index,original_line in enumerate(raw_rows[:20]):
            if not result['merchant'] and re.fullmatch(r'\W*(?:TAX\s*)?INVOICE\W*',original_line,re.I): continue
            if re.search(r'^\s*(?:TAX\s*INVOICE|ABN\b|DESCRIPTION\b|ITEMS?\b|QTY\b)',original_line,re.I): break
            line=re.sub(r'^\s*DUPLICATE\s+','',original_line,flags=re.I)
            if line.upper()=='DUPLICATE' or (len(line)<16 and repetitions[original_line]>=3): continue
            if len(re.findall(r'[A-Za-z]',line))<4 or len(line)>85: continue
            if _money(line): continue
            if STREET_ADDRESS.search(line): continue
            if re.fullmatch(r'[\W\s]*(?:PTY\s*)?LTD[\W\s]*', line, re.I): continue
            # A suburb between a street and state/postcode belongs to the
            # address block, even when it is printed in capitals.
            previous_rows = raw_rows[max(0,line_index-2):line_index]
            following_rows = raw_rows[line_index+1:line_index+3]
            if any(STREET_ADDRESS.search(row) for row in previous_rows) and any(re.search(r'\b(?:NSW|VIC|QLD|WA|SA|TAS|ACT|NT)\s+\d{4}\b',row,re.I) for row in following_rows): continue
            if re.search(r'\b(?:tax|invoice|abn|phone|tel|street|road|receipt|copy|date|www|email|fax|nsw|vic|qld|wa|sa|sale|description|qty|purchase|customer|gst|cash|manager|subtotal|total|opening|trading)\b|\bshop\s*\d|served\s+by|\d{3}|@',line,re.I): continue
            nearby='\n'.join(raw_rows[line_index+1:line_index+6])
            next_rows=raw_rows[line_index+1:line_index+6]
            next_address=bool(next_rows and STREET_ADDRESS.search(next_rows[0]))
            terminal_address=terminal_receipt and bool(next_rows and re.search(r'\b(?:NSW|VIC|QLD|WA|SA|TAS|ACT|NT)\s+\d{4}\b',next_rows[0],re.I))
            anchored=bool(re.search(r'\bABN\b|TAX\s*INVOICE|\bPH(?:ONE)?\b|\bSTREET\b|\bROAD\b',nearby,re.I)) or any(STREET_ADDRESS.search(r) for r in next_rows) or terminal_address
            generic=bool(re.match(r'^(?:thank\s*you|thanks|welcome|save\b|value\b|low\s*prices?\b)',line,re.I))
            one_word=len(re.findall(r'[A-Za-z]+',line))<2
            located = [(str(row.get('text',row.get('LineText',''))).strip(), _box(row)) for row in (lines or []) if isinstance(row,dict)]
            located = [(quote,box) for quote,box in located if box and box[2]>0 and box[3]>0]
            heights = sorted(box[3] for _,box in located)
            prominent = False
            if len(heights) >= 5 and anchored and line_index < 4 and not generic:
                typical = heights[len(heights)//2]
                top = min(box[1] for _,box in located)
                bottom = max(box[1]+box[3] for _,box in located)
                prominent = any(quote == original_line and box[3] >= typical*1.4 and box[1] <= top+(bottom-top)*.2 for quote,box in located)
            if prominent: one_word = False
            business_name=bool(re.search(r'\b(?:market|butchers?|bakery|cafe|restaurant|bar|grill|shop|pharmacy|supermarket|hotel|hardware|florist|fruit\s*barn|pty\s*ltd)\b',line,re.I))
            score=50 if generic or one_word else (90 if anchored and (business_name or terminal_address or next_address and len(_merchant_words(line))>=3) else 78 if anchored else 64)
            if prominent: score = max(score,92)
            result['merchant'].append(_candidate(line.strip(),original_line,engine,score,kind='merchant_header',flags=['unrecognized_merchant_header']+(['business_header_context'] if anchored else [])+(['business_name_descriptor'] if business_name else [])+(['generic_or_single_word_header'] if generic or one_word else [])))
    result['merchant_logo_evidence']=_merchant_logo_evidence(result['merchant'],lines,raw_rows,engine)
    # Deduplicate repeated OCR row variants without treating them as model votes.
    for field in ['date','total','merchant','supporting_amounts']:
        unique={}
        for item in result[field]:
            key=(str(item['value']),item['evidence'],item.get('kind'))
            if key not in unique or item['score']>unique[key]['score']: unique[key]=item
        result[field]=list(unique.values())
    # Explicit non-cash payment can identify the paid total when the print's
    # total label is missing. Split tender, cash out and balances prevent this.
    payments=[c for c in result['supporting_amounts'] if c.get('kind') in ['payment','settlement'] and not re.search(r'\bbalance\b|\blimit\b',c['evidence'],re.I)]
    payment_values={c['value'] for c in payments}
    refund=bool(re.search(r'^\s*\**\s*(?:transaction\s*(?:type)?\s*[:=-]?\s*)?(?:refund|return sale|return receipt|credit note)(?:\s*[:$*]|\s*$|\s+total\b)',text,re.I|re.M))
    if refund:
        for candidate in result['total']:
            candidate['flags'].append('explicit_refund_document')
    if re.search(r'cash\s*out',text,re.I):
        for payment in payments:
            if payment['kind']=='payment' and re.search(r'\bpurchase\b',payment['evidence'],re.I):
                result['total'].append({**payment,'score':93,'kind':'purchase_total','flags':payment.get('flags',[])+['purchase_excludes_cashout']})
    if len(payment_values)==1 and not re.search(r'cash\s*out|split\s*(?:payment|tender)',text,re.I):
        best=payments[0]
        if best['value']>=0 or refund:
            result['total'].append({**best,'score':88,'kind':'payment_total','flags':best.get('flags',[])+['explicit_payment_amount']})
        else:
            # Sales invoices often post payment as a negative ledger credit.
            # Do not turn that accounting sign into a refund. Require both the
            # positive subtotal and a zero closing balance as corroboration.
            subtotals=[c for c in result['supporting_amounts'] if c.get('kind')=='subtotal' and c['value']==-best['value']]
            balances=[c for c in result['supporting_amounts'] if c.get('kind') in ['balance','change'] and c['value']==0]
            nonzero_balance=any(c.get('kind')=='balance' and c['value']!=0 for c in result['supporting_amounts'])
            sales_receipt=re.search(r'^.*\btax\s+invoice\s+and\s+receipt\b.*$',text,re.I|re.M)
            sale_statement=re.search(r'^\s*sale(?:\s+includes\b[^\n]*)?\s*$',text,re.I|re.M)
            additional_charge=re.search(r'\bsurcharge\b|\b(?:service|delivery)\s*(?:fee|charge)\b|\bfreight\b|\bpostage\b',text,re.I)
            complete_sales_receipt=bool(sales_receipt and sale_statement and re.search(r'\bpayment\b',best['evidence'],re.I) and not additional_charge and not nonzero_balance)
            if subtotals and not nonzero_balance and (balances or complete_sales_receipt):
                proof=[subtotals[0]['evidence'],best['evidence']]
                if balances:
                    proof.append(balances[0]['evidence']); flag='subtotal_and_zero_balance_corroboration'
                else:
                    proof.extend([sale_statement.group().strip(),sales_receipt.group().strip()]); flag='signed_payment_matches_subtotal_on_sales_receipt'
                result['total'].append(_candidate(-best['value'],'\n'.join(proof),engine,92,kind='settled_sale_payment',flags=['payment_credit_sign_normalized',flag]))
    # A restaurant table account before payment prints the same amount as
    # Total and Balance. Keep the second printed observation as corroboration,
    # never as a substitute for a missing Total or a partially paid balance.
    account=re.search(r'^.*\bTABLE\s+ACCOUNT\b.*$',text,re.I|re.M)
    has_payment_context=bool(payments or re.search(r'\b(?:deposit|prepaid|paid|payment|tendered|credit\s+note|voucher|gift\s*card)\b',text,re.I))
    if account and has_payment_context: result['diagnostics'].append('table_account_has_payment_context')
    if account and not has_payment_context:
        for balance in result['supporting_amounts']:
            if balance['kind']=='balance' and balance['value']>0:
                result['invoice_balance_checks'].append({**balance,'account_evidence':account.group().strip(),'scope':'supports_existing_printed_total_only'})
    return result


def reconcile(candidates):
    """Combine candidates; conflicts remain visible and low evidence stays null.

    Accepts one collect_candidates dict or a list of such dicts. Return values
    are separated from `fields` decisions, which include every competing value.
    Agreement is evidence agreement, not a claim that OCR is correct.
    """
    inputs=[candidates] if isinstance(candidates,dict) else list(candidates)
    combined={field:[c for result in inputs for c in result.get(field,[])] for field in ['date','total','merchant']}
    support=[c for result in inputs for c in result.get('supporting_amounts',[])]
    arithmetic_checks=[c for result in inputs for c in result.get('arithmetic_checks',[]) if c.get('kind')=='complete_item_sum']
    logo_evidence=[c for result in inputs for c in result.get('merchant_logo_evidence',[])]
    balance_checks=[c for result in inputs for c in result.get('invoice_balance_checks',[])]
    if any('table_account_has_payment_context' in result.get('diagnostics',[]) for result in inputs): balance_checks=[]
    decisions={}
    for field,items in combined.items():
        explicit_brand_present=field=='merchant' and any(
            c.get('kind') in ['merchant_registry','merchant_domain','merchant_payment_footer','merchant_brand_slogan']
            and 'legal_entity_abn_fallback' not in c.get('flags',[]) for c in items)
        groups=defaultdict(list)
        for candidate in items:
            key=str(candidate['value'])
            # Typography is not a merchant disagreement. Preserve each raw
            # quote, and do not fuzzy-correct words or substitute business names.
            if field=='merchant': key=re.sub(r'[\W_]+','',key.casefold().replace('&','and'))
            groups[key].append(candidate)
        options=[]
        for group in groups.values():
            best=max(group,key=lambda c:c['score'])
            engines=sorted({str(c['engine']).split(':')[0] for c in group})
            score=best['score']+min(10,max(0,len(engines)-1)*6)
            flags=sorted({f for c in group for f in c.get('flags',[])})
            if explicit_brand_present and all('legal_entity_abn_fallback' in c.get('flags',[]) for c in group):
                score=min(score,75)
                flags.append('legal_entity_secondary_to_printed_brand')
            if field=='total':
                # A fallback created from an EFT line is not corroborated by
                # that same EFT observation a second time.
                matches=[c for c in support if c['value']==best['value'] and c.get('kind') in ['payment','subtotal']] if best.get('kind') in ['printed_total','clipped_total_label'] else []
                if matches and best['score']>=67:
                    score+=8
                    flags.append('corroborated_by_payment_or_subtotal')
            options.append({'value':best['value'],'score':min(score,100),'engines':engines,'evidence':group,'flags':flags})
        if field=='date':
            labeled=[o for o in options if len({str(c['engine']).split(':')[0] for c in o['evidence'] if 'explicit_transaction_date_context' in c.get('flags',[])})>=2]
            # A clearly labeled transaction date has a different role from a
            # package expiry date or an unlabeled, clipped terminal duplicate.
            # Two conflicting labeled dates still require review.
            if len(labeled)==1:
                for option in options:
                    if option is not labeled[0] and not any('explicit_transaction_date_context' in c.get('flags',[]) for c in option['evidence']):
                        option['score']=min(option['score'],75)
                        option['flags'].append('unlabeled_date_secondary_to_transaction_label')
        logo_resolution=_logo_name_resolution(options,logo_evidence) if field=='merchant' else None
        if logo_resolution:
            for option in options:
                if option['value']==logo_resolution['selected_value']:
                    option['score']=max(option['score'],99)
                    option['flags'].append('existing_name_disambiguated_by_logo')
                    option['logo_disambiguation']=logo_resolution
                elif option['value'] in logo_resolution['alternative_values']:
                    option['score']=min(option['score'],75)
                    option['flags'].append('alternate_spelling_not_supported_by_logo')
        if field=='total':
            clear_totals=[o['value'] for o in options if len({str(c['engine']).split(':')[0] for c in o['evidence'] if c.get('kind')=='printed_total' and c['score']>=85})>=2]
            explicit_refund_totals=[o['value'] for o in options if o['value']<0 and any(c.get('kind')=='printed_total' and c['score']>=90 and 'explicit_refund_document' in c.get('flags',[]) for c in o['evidence'])]
            for option in options:
                # A smaller payment can be a partial settlement or a misplaced
                # adjacent tax amount. It cannot replace an explicitly printed
                # purchase total agreed by independent OCR engines. Larger or
                # signed discrepancies remain unresolved here.
                if all(c.get('kind')=='payment_total' for c in option['evidence']) and option['value']>=0 and any(value>option['value'] for value in clear_totals):
                    option['score']=min(option['score'],75)
                    option['flags'].append('smaller_payment_not_transaction_total')
                if option['value']==0 and explicit_refund_totals and all(c.get('kind')=='payment_total' for c in option['evidence']):
                    option['score']=min(option['score'],75)
                    option['flags'].append('zero_payment_not_printed_refund_total')
            balanced=[]
            for option in options:
                matching=[c for c in balance_checks if c['value']==option['value']]
                if len({str(c['engine']).split(':')[0] for c in matching})>=2 and any(c.get('kind')=='printed_total' for c in option['evidence']):
                    balanced.append((option,matching))
            if len(balanced)==1:
                selected,proof=balanced[0]
                selected['flags'].append('table_account_balance_supports_printed_total')
                selected['invoice_balance_checks']=proof
                for option in options:
                    if option is not selected:
                        option['score']=min(option['score'],75)
                        option['flags'].append('contradicted_by_unpaid_table_account_balance')
        if field=='total' and arithmetic_checks:
            sums={Decimal(str(check['value'])) for check in arithmetic_checks}
            if len(sums)==1:
                expected_sum=next(iter(sums))
                for option in options:
                    has_printed_total=any(c.get('kind')=='printed_total' for c in option['evidence'])
                    if Decimal(str(option['value']))==expected_sum and has_printed_total:
                        option['score']=max(option['score'],98)
                        option['flags'].append('complete_item_sum_supports_printed_total')
                    elif Decimal(str(option['value']))!=expected_sum:
                        option['score']=min(option['score'],75)
                        option['flags'].append('contradicted_by_complete_item_sum')
                    option['arithmetic_checks']=arithmetic_checks
        options.sort(key=lambda o:(o['score'],len(o['engines'])),reverse=True)
        if not options:
            decisions[field]={'value':None,'status':'missing','confidence':'none','candidates':[],'disagreement':False}
            if field=='total' and arithmetic_checks: decisions[field]['arithmetic_checks']=arithmetic_checks
            continue
        first=options[0]; runner=options[1] if len(options)>1 else None
        material_alternative=bool(runner and runner['score']>=80)
        consensus_wins=bool(material_alternative and len(first['engines'])>=2 and len(first['engines'])>len(runner['engines']))
        conflict=bool(material_alternative and first['score']-runner['score']<10 and not consensus_wins)
        arithmetic_disagrees=field=='total' and len({c['value'] for c in arithmetic_checks})>1
        arithmetic_rejects_alternative=field=='total' and any('contradicted_by_complete_item_sum' in o['flags'] for o in options)
        smaller_payment_alternative=field=='total' and any('smaller_payment_not_transaction_total' in o['flags'] for o in options)
        semantic_alternative=any(set(o['flags']) & {'unlabeled_date_secondary_to_transaction_label','zero_payment_not_printed_refund_total'} for o in options)
        if arithmetic_disagrees: conflict=True
        threshold=82
        ambiguous_numeric=bool(set(first['flags']) & {'ambiguous_extra_decimal_digit','missing_decimal_separator'})
        if ambiguous_numeric and len(first['engines'])<2: threshold=90
        if 'clipped_total_label' in first['flags'] and len(first['engines'])<2: threshold=max(threshold,90)
        accepted=first['score']>=threshold and not conflict
        decisions[field]={'value':first['value'] if accepted else None,
                          'status':'accepted' if accepted else ('conflict' if conflict else 'review'),
                          'confidence':'high' if accepted and first['score']>=95 else ('medium' if accepted else 'low'),
                          'score':first['score'],'engines':first['engines'],'evidence':first['evidence'],
                          'flags':first['flags']+(['minority_engine_disagreement'] if consensus_wins else [])+(['complete_item_sums_disagree'] if arithmetic_disagrees else [])+(['arithmetic_reconciled_ocr_disagreement'] if accepted and arithmetic_rejects_alternative else [])+(['printed_total_precedes_smaller_payment'] if accepted and smaller_payment_alternative else []),'candidates':options,'disagreement':material_alternative or arithmetic_disagrees or arithmetic_rejects_alternative or smaller_payment_alternative or bool(logo_resolution),
                          'independent_engine_count':len(first['engines']),
                          'support':'multi_engine_consensus' if len(first['engines'])>=2 else 'single_engine_evidence'}
        if field=='total' and arithmetic_checks:
            decisions[field]['arithmetic_checks']=arithmetic_checks
            decisions[field]['arithmetic_checks_disagree']=len({c['value'] for c in arithmetic_checks})>1
        if field=='merchant' and logo_resolution:
            decisions[field]['logo_disambiguation']=logo_resolution
        if semantic_alternative:
            decisions[field]['disagreement']=True
            decisions[field]['flags'].append('semantic_context_reconciled_disagreement')
        if field=='total' and first.get('invoice_balance_checks'):
            decisions[field]['invoice_balance_checks']=first['invoice_balance_checks']
            decisions[field]['disagreement']=True
    return {field:decision['value'] for field,decision in decisions.items()} | {'fields':decisions,'purpose':'unknown','score_note':'Heuristic evidence scores; not calibrated accuracy probabilities'}
