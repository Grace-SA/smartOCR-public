"""Assemble a frozen complete-image set from visual qualification, never OCR scores."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from receipt_engine import ROOT,read_json,write_json,now

def assemble(freeze=False):
    sources=[('research/visibility_audit/reusable_complete_manifest.json','research/visibility_audit/reusable_reference.json'),
             ('research/complete_candidates.json','research/complete_reference_additional.json'),
             ('research/complete_extra_manifest.json','research/complete_extra_reference.json')]
    records=[]; refs=[]; seen_hash=set(); seen_identity=set()
    for manifest_path,ref_path in sources:
        manifest=read_json(ROOT/manifest_path,[]); ref_data=read_json(ROOT/ref_path,[])
        references={r['id']:r for r in ref_data}
        for item in manifest:
            ref=references.get(item['id'])
            if not ref or any(ref.get(f) is None for f in ['merchant','date','total']):continue
            image=(ROOT/item['local_path']).resolve()
            digest=hashlib.sha256(image.read_bytes()).hexdigest()
            # Same original image/crop and same annotated transaction is a duplicate.
            identity=(item.get('source_page_url') or item.get('source_url'),ref['merchant'],ref['date'],str(ref['total']))
            if digest in seen_hash or identity in seen_identity: continue
            seen_hash.add(digest); seen_identity.add(identity)
            # A whitelist prevents reference annotations from entering the input manifest.
            record={k:item.get(k) for k in ['id','source_page_url','source_url','image_url','source_family','source_kind','license','licence_status','attribution','quality_flags','transformation'] if item.get(k) is not None}
            record.update(local_path=str(image.relative_to(ROOT)),sha256=digest,kind='public_sample',currency_hint='AUD',qualification='merchant_date_final_total_visually_readable_before_new_OCR_evaluation')
            records.append(record); refs.append({**ref,'source_image_sha256':digest})
    if freeze and len(records)<100: raise RuntimeError(f'Only {len(records)} qualified unique images, cannot freeze 100')
    suffix='' if freeze else '_draft'
    destination=ROOT/f'research/validation100{suffix}_manifest.json'
    if freeze and destination.exists():raise RuntimeError('Frozen manifest already exists; do not silently replace benchmark images')
    records=records[:100]; refs=refs[:100]
    write_json(destination,records); write_json(ROOT/f'research/validation100{suffix}_reference.json',refs)
    write_json(ROOT/f'research/validation100{suffix}_selection.json',{'created_at':now(),'count':len(records),'frozen':freeze,'manifest_sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),'criterion':'Image-visible merchant, complete transaction date, final transaction total. No OCR success metrics used for inclusion.','source_manifests':[s[0] for s in sources]})
    print(json.dumps({'count':len(records),'frozen':freeze,'manifest':str(destination.relative_to(ROOT))}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--freeze',action='store_true');a=p.parse_args();assemble(a.freeze)
