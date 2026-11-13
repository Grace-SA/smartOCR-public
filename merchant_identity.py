"""Small, source-backed public identity cache; never receipt-specific answers.

Legal-entity enrichment is distinct from reading a trading logo and requires
review. Unknown ABNs are not guessed or looked up over the network at runtime.
"""
import re

VERIFIED_ABNS={
    '60650692934':{
        'name':'Mid Western Auto Electrics & Air Conditioning Pty Ltd',
        'source':'https://abr.business.gov.au/ABN/View?id=60650692934',
        'verified_on':'2026-11-13',
    },
}


def verified_supplier_candidates(text,engine,registry=None):
    registry=VERIFIED_ABNS if registry is None else registry
    rows=text.splitlines()[:40]; prefix=[]; found=[]
    for row in rows:
        if re.search(r'\b(?:bill\s*to|ship\s*to|sold\s*to|invoice\s*to|recipient)\b|\bcustomer\s*:',row,re.I): break
        prefix.append(row)
        match=re.search(r'\bA\.?B\.?N\.?\s*:?\s*((?:\d[ .\t]*){11})(?!\d)',row,re.I)
        if not match: continue
        abn=re.sub(r'\D','',match[1]); identity=registry.get(abn)
        if not identity: continue
        words=set(re.findall(r'[a-z]+',identity['name'].lower()))-{'and','pty','ltd','limited','the'}
        printed=set(re.findall(r'[a-z]+',' '.join(prefix).lower()))
        # The ABN alone cannot distinguish a corporate owner from its banners.
        if len(words & printed)<3: continue
        found.append({'value':identity['name'],'evidence':row,'engine':engine,'score':88,
                      'kind':'merchant_verified_abn','registry_reference':identity['source'],
                      'registry_verified_on':identity['verified_on'],
                      'flags':['legal_entity_abn_fallback','external_legal_identity_requires_review']})
    return found
