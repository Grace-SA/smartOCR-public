# OCR accuracy review — 13 November 2026

## Decision

Continue development. This patch fixes reproducible extraction and verification
errors; it does **not** establish 100% OCR accuracy, an improvement on the real
photo population, or production readiness. No model inference was run here.

The current repository reports a frozen 100-image evaluation with 11/100 strict
merchant matches, 86/100 dates, 65/100 amounts and 7/100 complete three-field
matches. Its references are assistant annotations, not independently audited
human ground truth, and 73% of samples are transport receipts. The later
12-photo development pilot has 7/10 complete matches using the ensemble and
5/10 using the structured fast route. These are different datasets and must
not be presented as an accuracy trend. The previously tuned development-set
100/100 is not a generalization result.

## Changes and reproducible failures

- A known brand on a priced product or street-address row could override the
  actual merchant header. Registry matching now excludes those rows while
  retaining ordinary numbered brand headers.
- Accounting parentheses, CR suffixes, and minus signs after currency symbols
  could lose their negative sign. Printed signs now remain part of the amount
  evidence. Unbalanced accounting parentheses abstain.
- Space, NBSP and narrow-NBSP thousands could lose leading digits. Valid
  groupings are parsed as a whole; malformed numeric fragments are rejected.
- Confidence and live pilot scoring used ASCII-only merchant comparison,
  making different Chinese names equal to the same empty key. Unicode letters,
  numbers and combining marks are retained. Punctuation-only values cannot
  confirm a merchant. Canonically equivalent accents and the existing
  punctuation/case/ampersand rules remain comparable.
- Two parser tests unnecessarily required a private image even though OCR was
  supplied. They now use temporary synthetic bytes solely for hashing.

The live confidence policy is versioned `evidence-v3-2026-11-13`. The two live
scorers report `unicode-merchant-v2-2026-11-13`. The frozen blind-test scorer,
old results, references, and predictions are deliberately unchanged. A future
fresh benchmark must freeze the new scoring policy before inspecting outputs.

## Review and validation limits

Self-review and independent source review were performed using synthetic OCR
transcripts. Tests validate parsing, evidence handling and scoring, not the
ability of a vision model to read a photograph. A regression found during
review in handling multiple amounts on one row was blocked before submission.

This cloud checkout has no receipt photos, private annotations, saved real OCR
predictions, Mac/Metal models or local OXR service. No receipt data was uploaded,
changed or committed. End-to-end model, Mac workflow and browser validation were
not run. The full baseline Python suite initially had 10 environment errors:
two unavailable private image fixtures and eight export/font/runtime errors.
The fixture dependency was removed; export runtime limitations remain.

Final validation: 183 Python tests ran, 175 passed and eight errored on missing
font/Excel-renderer dependencies. The independently selected non-export suite
passed all 167 tests; six Node tests, JavaScript syntax and Python compilation
passed. Twelve Python regression tests were added. This is not a full green
application run. The export errors were present in the baseline and were not
hidden by changing or disabling those tests.

## Required next accuracy experiment

1. On the original model host, audit development references and transaction
   boundaries. Keep the 49 reserved grouped samples untouched for selection.
2. Replay a new, immutable development experiment with the same model settings,
   images and first-attempt accounting. Preserve the baseline and all failures.
3. Review merchant/logo, layout/reading order and final-total role errors against
   original pixels. Improve these from development examples only.
4. Freeze candidate code, model/settings hashes, sample manifest and scoring
   before first-attempt inference on the reserved group. Do not tune against it.
5. Report merchant/date/amount accuracy, complete-record accuracy, missing fields,
   automatic-confirmation precision and coverage, and latency together. Missing
   or refused outputs stay in their appropriate denominators. Document sample
   diversity and reference uncertainty.

Even a perfect finite held-out result is a result for that dataset, not a
guarantee that every future receipt will be correct. The application must retain
review and correction pathways. Product feasibility remains tied to reliably
reducing review work at acceptable latency; adding accounts or billing does not
resolve the core extraction gap. Existing competitor workflow evidence remains
in `COMPETITOR_WORKFLOWS.md`; this patch makes no new market-size claims.
