# smartOCR

A local Australian receipt workspace: import photos, extract merchant/date/total with three OCR models, organise categories and tags, review exceptions, export records and generate insights. No account or email integration is required.

Development records: [milestone status](docs/STATUS.md), [engineering journal](docs/DEVELOPMENT.md), [competitor workflow research](docs/COMPETITOR_WORKFLOWS.md), [receipt structure and evaluation](docs/RECEIPT_STRUCTURE.md), [setup and limitations](docs/SETUP.md). Real receipt data and generated evidence stay local and are not included in this source repository.

Latest milestone: [real-receipt pilot results and open issues](docs/PHASE_SUMMARY.md). The fast OCR route remains experimental.

## Open the workspace

Double-click `start.command` on this Mac and open **http://127.0.0.1:8765/**. The server listens only on loopback. Transfer phone photos to this Mac to import them. Each batch accepts 1–40 JPG, PNG, WebP, HEIC or TIFF images, up to 24 MB each.

## Workflow

- **Needs review** shows uncertain extractions. **Auto-confirmed** contains records supported by the confidence policy. **Reviewed by you** contains explicit confirmations and corrections.
- Open any receipt to inspect the original photo, field evidence, competing readings, confidence reasons and correction history. Every receipt remains editable.
- **Categories** opens category-specific lists. Select several records to apply a category together. Purpose (work/personal) is separate and requires the user's context.
- Filter by merchant, category, purpose, date, amount, currency, completeness, tag or confidence. Export **All receipts**, **Current results** or **Selected receipts** as Excel, PDF, CSV or JSON.
- **Insights** immediately displays computed totals and category, merchant and monthly breakdowns for the chosen scope. **Generate AI insight** asks local AI to prioritise applicable actions; numerical and status statements come from the computed records. A model error or timeout does not remove the statistics. Download the same report snapshot as HTML, PDF or JSON.

Refunds retain their signs. Zero and missing amounts remain different. Currencies are summarised separately. Receipt PDF exports contain scoped statistics by category, month and merchant, followed by receipt information. Original photos are excluded from normal exports. Standard JSON contains scoped statistics and receipt information. Raw evidence is retained in the database; internal archival export can include it explicitly.

## Confidence and corrections

`receipt_confidence.py` implements the versioned evidence policy. Automatic confirmation requires valid merchant/date/total, accepted extractions, at least two distinct uncapped model supports per field, no conflicting values or unsafe evidence flags, and complete outputs from all three OCR engines. Multiple crops from one engine count as one model.

The index is **evidence strength, not a calibrated probability or a guarantee**. It covers the three extraction fields; categories, tags and purpose remain separate. The blind evaluation measures automatic-confirmation coverage and precision.

Correcting a core field records a user override, preserves the original extraction and adds before/after values to the audit trail. Editing notes, purpose or category preserves confirmation status. Reopening a receipt keeps it in review until the user confirms it again.

The development workspace was backed up under `data/snapshots/before-english-confidence-*.json`. Its 100 core extraction values and evidence were preserved; the initial policy routes 66 to automatic confirmation and 34 to review. See `output/qa/workflow-migration.json`.

## Development set and independent blind test

The previous fixed development set reached 100/100 matching merchant, date and total after tuning. It is **not** an independent accuracy measurement. Its manifest, references and predictions remain under `research/validation100_*` and `research/evaluations/validation100/`. The original earlier 100 samples and baseline also remain intact. The historical quality page is `output/quality/index.html`.

The new blind test is isolated under `research/blind100/`:

- `freeze.json` and `frozen_app/`: exact extraction code and inventory of previously seen images.
- `external_inputs.json`: model runner/manifest hashes and test hardware.
- `manifest*.json`, `sampling_protocol.json`, `manifest_revision_journal.json`: new transactions and documented image preparation.
- `references.json`: independent visual annotations, never supplied to inference. These are assistant annotations, not an independently human-reviewed gold standard.
- `confidence_policy.py` and `confidence_freeze.json`: confidence policy fixed before inspecting predictions.
- `runs/`: first-attempt status, timeout and elapsed time for each image, including failed attempts.
- `predictions/`: saved uncorrected extraction results and confidence decisions.
- `scoring_freeze.json`: exact scoring policy fixed before prediction inspection. Merchant matching ignores case, spaces and punctuation, treating & as and; date and cent amount are exact.
- `evaluation.json` and `output/quality/blind100.html`: generated once scored. Check `complete` and the actual denominator before interpreting results.

Public FOI documents overrepresent travel and transport receipts and repeated layouts. Source diversity and annotation uncertainty are reported alongside accuracy. No selected image is replaced because OCR fails. New-sample rules are not tuned during this test.

```sh
# Run new images sequentially; recorded first attempts are never rerun.
python3 scripts/run_blind100.py --manifest research/blind100/manifest.json
# Score saved predictions only, after all 100 first attempts finish.
python3 scripts/evaluate_blind100.py
# Unit tests do not require model inference.
python3 -m unittest discover -s tests -q
```

The scripts use the installed Codex Python runtime. Inference needs access to Metal. Do not start a second blind runner while one is active. Timings include cold model-process loading and existing retries, but exclude download, annotation and optional AI classification. This Mac may also run another project's GPU workload.

## Extraction and local dependencies

PaddleOCR, Unlimited OCR 2 and OXR run on this Mac using existing sibling projects' model environments. Installation details are in `research/ocr_reuse_notes.json`. OXR uses the existing layout service at `127.0.0.1:18081`.

The pipeline retains full model outputs, image hashes, crop mappings, output-limit indicators and field evidence. Empty/capped outputs and field conflicts trigger bounded existing retries. Arithmetic may corroborate an independently read total only when all required item/discount evidence is complete; it cannot invent a missing total. Classification and report commentary use optional Apple Foundation Models and cannot modify core extraction fields.

This prototype depends on this Mac's model paths, OXR service, Codex Python/Node/artifact-tool runtime and optional Apple Intelligence. It is not a portable production deployment. Public sample receipts describe different people and periods, not one person's spending history. Source provenance and reuse limitations are preserved.

`scripts/process_samples.py` is the historical baseline and can rebuild the workspace; it is not the current workflow. Historical Chinese documentation is retained in `research/README-before-english-workflow.md`.

## Workflow revision after the frozen blind test

Live photo imports now skip the expensive secondary OXR focus and field-detail retry cascade; all three primary engines still run. This is a latency tradeoff, not a proven accuracy improvement. The frozen blind run continues with its original retry policy. Unknown values remain reviewable. Date/category/refund tags are generated automatically, while personal/work purpose requires user context. Generic company suffixes and suburb lines inside address blocks are excluded from merchant candidates; full logo/layout-aware extraction remains under evaluation.

Final frozen blind results (100 unseen transactions): merchant strict name matching11/100, date86/100, amount65/100, all three strict fields7/100; automatic coverage4/100. Three automatic name nonmatches faithfully reproduce a printed legal-name suffix omitted by the reference. Total processing7430.67s, median58.83s, P95155.36s, maximum474.95s. These are frozen-v1 results; product-v2 changes are unmeasured on a new blind set. See output/quality/blind100.html and output/exports/blind100-evaluation.xlsx. References were assistant visually reviewed, not human gold;73%transport.

Single known slow-case follow-up: product-v2 processed blind050 in22.18s versus frozen-v1 474.95s. Different run conditions and retry policy; not a population speed estimate. Total remained unavailable and the receipt stayed in review. Current development workspace:69 automatic,30 review,1 user-confirmed;100 have automatically generated tags.
