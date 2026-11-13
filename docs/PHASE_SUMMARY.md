# Real-receipt pilot and workflow milestone — 13 November 2026

The local workflow and source repository are usable. A faster production extraction route has **not** been established. The real-photo pilot exposed merchant/structure failures that were hidden by the earlier tuned development set.

## Subsequent accuracy stage

The new 27-photo development comparison improves all three fields from 10/20 complete receipts on the first attempt to 20/20 after revised parsing and grounded local image review. The original pilot retains 10/10 complete receipts. Merchant matching uses predeclared aliases; one missing-merchant control remains unresolved. These are tuned development results, not an independent 100-photo pass.

Uncertain live imports now use the local visual helper when installed, with changed fields kept for review and existing human corrections preserved. A fresh runtime smoke passed in 21.67 seconds for the visual step alone. The full three-model expanded first attempt took 46.5 minutes for 27 photos under shared workload, so production throughput remains unresolved. Details: [accuracy stage report](ACCURACY_STAGE.md).

## Subsequent product and interaction revision

After pushing the accuracy stage, a second revision makes exception review field-specific, adds confirm/skip navigation and protects unsaved edits. Date presets include Australian financial years; removable filters and ready-only export preview make report scope explicit. The insights action opens computed statistics immediately, with AI guidance generated separately.

Verification: 206 Python tests and 11 Node tests passed. Browser checks on a separate data copy covered confirmation, skipping, discard, preserved overrides, empty ready-only export and a two-receipt AUD 49.95 Excel/insights scope. Desktop and 319px mobile layouts were checked; main data remains unchanged. These workflow checks do not extend the extraction accuracy claims above.

## Deliverables

- Private source repository: [Grace-SA/smartOCR](https://github.com/Grace-SA/smartOCR). Receipt photos, annotations, OCR output and generated files remain local and ignored by Git.
- Dataset inventory and reproducible first-attempt benchmark/scoring tools. All 276 supplied photos decode; initial grouping reserves 49 images, uses 173 for development and quarantines 54 pending document/privacy/ambiguity decisions. There are no exact pixel duplicates; repeated transactions still need checking.
- English workflow improvements: All receipts entry, optional metadata folded away, image zoom, save-and-next review and a scoped export preview. If data changes after preview, the API refuses the stale export.
- Separate experimental resident-model and fast local-AI routes. Neither changes the default three-model extraction route or silently certifies a receipt.
- Development journal, receipt structure notes, competitor research and setup instructions.

## Measured comparison

Same 12 selected development photos, sequential runs on an Apple M3 Max / 48 GB. Each run uses new IDs; preprocessing and model startup are included. References are assistant visual readings, not independently human-verified ground truth. Ten photos have all three fields visible; two are partial-document controls. One reference correction is explicitly retained in the local revision journal.

| Route | Total wall time | Median / P95 per photo | Merchant | Visible date | Visible total | All three, complete references | Auto-confirmed |
|---|---:|---:|---:|---:|---:|---:|---:|
| Three-model baseline | 405.6s | 33.44s / 48.05s | 10/12 | 10/10 | 9/11 | 7/10 | 2/12 |
| Resident ensemble | 406.1s | 33.46s / 52.34s | 10/12 | 10/10 | 9/11 | 7/10 | 2/12 |
| Paddle + unstructured local AI | 74.5s | 5.77s / 9.24s | 6/12 | 10/10 | 9/11 | 4/10 | 0/12 |
| Paddle + structured local AI | 86.2s | 6.60s / 10.65s | 6/12* | 10/10 | 10/11 | 5/10 | 0/12 |

\* Accepted merchant aliases were fixed before inference. Structured fast-route strict merchant matching is 5/12; the other rows' strict scores equal their displayed merchant scores. All four routes abstained on the two absent dates and one absent amount. These abstentions are not counted as successful field extraction.

No nonmatching automatic confirmations occurred among the two automatically confirmed baseline/resident receipts; this sample is far too small to estimate production precision. Zero automatic confirmations in the quick route gives no evidence of automatic precision. The quick route omits the baseline's optional AI categorisation step, so this is not a feature-parity throughput comparison. Shared hardware, model/OS caches and one run per route limit conclusions about repeatability. P95 uses nearest rank; with 12 photos it is the maximum.

## Interpretation

1. Keeping some models loaded produced no end-to-end gain here. OXR still reloads, and model/AI latency dominates; do not present residency as a demonstrated speed improvement.
2. A single-Paddle route is materially faster, but missing/incorrect merchants remain. The structured route improves one final-amount case while still resolving only five complete receipts correctly. It is not ready to replace the ensemble.
3. The first quick run's AI output failed the expected field schema in all 12 cases. Guided generation fixed the JSON contract. All 12 structured responses contained at least one grounded field, but 14 field suggestions were rejected because their source citations did not support the proposed values. Preserving these failures is essential to diagnosing the model, not just the parser.
4. Exact OCR evidence is a necessary check, not sufficient proof of semantic correctness. Supplier, payment provider, address, customer, document title, amount due, tax and final payment require distinct roles. Text-only AI cannot see a logo omitted by OCR.
5. This pilot is development material. The reserved 49 photos have been seen as grouping thumbnails but have not been inferred or fully annotated; they are not a claim of wholly unseen pixels. The previous independent 100-image run is preserved and is not superseded by these pilot scores.

## Workflow verification

- 171 Python tests and six Node tests passed; JavaScript syntax check passed.
- Browser: desktop and 390px mobile, photo zoom, collapsed optional fields, save-and-next, user correction and filtered export preview.
- Separate synthetic database: an amount changed from 20.00 to 23.50, with original extraction and user edit history retained. Scoped JSON, Excel and PDF exports completed through the UI.
- Read back the scoped files: exactly one receipt, AUD 23.50; the PDF contains no original images. The main public-data CSV also exported successfully.
- AI report QA found a hallucinated confirmation count expressed in words, bypassing the old digit filter. Replaced free-form factual prose with AI selection of allowed action IDs and deterministic text. The live local-AI retest produced valid guidance on its first attempt, with the scope still showing zero automatic and one human confirmation. This is AI-prioritised workflow guidance, not unrestricted spending analysis.
- Export API tests cover matching snapshots, changed amounts, changed tags and malformed previews.
- Main receipt database hash was unchanged during QA. Screenshots, detailed timings and private references are local-only.

## Next acceptance gates

1. Independently audit more development references and define one-transaction boundaries before processing multi-document/partial photos as normal receipts.
2. Improve layout and visually grounded merchant/amount interpretation; compare conditional escalation with full three-model processing, including classification cost.
3. Freeze the candidate and evaluate the reserved set once. Publish accuracy, review coverage, erroneous automatic confirmations, median/P95 and batch wall time together.
4. Package the model dependencies independently of sibling projects before testing on another computer.

The release decision remains **continue the local prototype, do not claim 100% accuracy or production readiness**. Accounts, mailbox ingestion, email archives and cloud sync are outside this milestone.
