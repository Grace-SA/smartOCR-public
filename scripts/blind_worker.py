"""One isolated first-pass receipt run, importing only the frozen implementation."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time

p=argparse.ArgumentParser();p.add_argument('--frozen-root',required=True);p.add_argument('--item',required=True);p.add_argument('--out',required=True)
a=p.parse_args();frozen=Path(a.frozen_root).resolve()
sys.path.insert(0,str(frozen))
from receipt_pipeline import extract_ensemble_record
import receipt_pipeline

# Classification cannot alter the three extraction fields. It is deliberately
# outside the measured OCR workload and outside the accuracy comparison.
receipt_pipeline._apply_classification=lambda record,allow_model:record
item=json.loads(Path(a.item).read_text());started=time.monotonic()
record=extract_ensemble_record(frozen/item['local_path'],source={'kind':'blind_sample'},record_id=item['id'],run_models=True)
elapsed=time.monotonic()-started
spec=importlib.util.spec_from_file_location('frozen_confidence',frozen.parent/'confidence_policy.py')
policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(policy)
policy.apply_confidence(record)
record['blind_timing']={'ocr_pipeline_seconds':round(elapsed,4),'classification_included':False,
    'scope':'Image preparation, three actual models, existing automatic retries/detail review, reconciliation; per-process model loading included. Download and reference annotation excluded.'}
out=Path(a.out);out.parent.mkdir(parents=True,exist_ok=True)
temporary=out.with_suffix('.tmp');temporary.write_text(json.dumps(record,ensure_ascii=False,indent=2));temporary.replace(out)
print(json.dumps({'id':item['id'],'elapsed_seconds':round(elapsed,3),'ensemble_status':record['ensemble_status']}),flush=True)
