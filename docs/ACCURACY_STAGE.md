# Receipt accuracy development — 2026-11-13

## Acceptance definition

Merchant, transaction date and gross document total must each match independently annotated visible evidence. Report both exact merchant spelling and predeclared brand/legal-name aliases. Missing or cropped information is an abstention control, not a correct extraction. A successful process exit or populated JSON object is not a correct receipt. Automatic-confirmation precision and coverage are separate measurements. Human overrides remain authoritative.

The present references were read visually by the assistant before each first attempt. They still require an independent human audit. A 100% result on these development photos does not establish 100% accuracy on future receipts.

## Changes

- Separate gross total, included tax, item total, paid amount and remaining balance; support terminal SALE/AUD blocks without crossing accounting labels.
- Recover accounting summary and transaction-date columns from OCR HTML tables with rowspan/colspan alignment. Do not sum product rows to invent absent totals.
- Distinguish supplier FROM blocks, customer TO blocks, document titles, corner addresses and generic outlet headings.
- Extend the printed-brand registry with source-backed Harvey Norman, Supercheap Auto and Auto One entries. A brand must appear in identity evidence; competitor mentions are excluded.
- Add a small public ABN identity cache for stylised logos, requiring both the supplier ABN and at least three matching printed name words. It is legal-entity enrichment, not raw OCR; it always blocks automatic confirmation. Unknown ABNs are not guessed. The current new entry is [verified in ABN Lookup](https://abr.business.gov.au/ABN/View?id=60650692934); this development-added cache entry does not prove unseen-merchant generalisation.
- Distinguish a bank terminal's merchant heading from a retail header containing only its suburb, using the EFTPOS heading, MID/TID block and business descriptor.
- Add immutable cache replay and separate visual reconciliation experiment tools. References never enter model prompts, extraction or reconciliation.
- Try a local image-language model as an independent image reader. Changed fields need grounded OCR role evidence and remain reviewable. Unsupported model suggestions cannot silently replace extracted values. The live import path invokes it for uncertain records when the verified local model is installed; it cannot automatically confirm changed fields.
- Bound new full-engine subprocess runs to 180 seconds per image. An exhausted budget is unavailable evidence. The ongoing first-attempt batch used the earlier unbounded runner and is preserved as such.

## Local visual model provenance

`mlx-community/Qwen3-VL-8B-Instruct-4bit`, revision `defcdea7cc7a4b0858fea563cbbce171d328e457`, MLX-VLM 0.7.12, temperature 0, 600-token limit, 1,572,864 maximum image pixels. Model weights were downloaded once; both weight shards were checked against download ETag SHA-256 values. Inference runs offline, with `trust_remote_code=False`; receipt images are not uploaded. Model weights and source receipts are excluded from Git.

Sources: [original model card](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct), [MLX quantization](https://huggingface.co/mlx-community/Qwen3-VL-8B-Instruct-4bit), [MLX-VLM usage](https://github.com/Neywa-Labs/mlx-vlm/blob/main/docs/usage.md). Vendor capabilities are not measured receipt accuracy.

Registry identity sources: [Harvey Norman](https://www.harveynorman.com.au/about-harvey-norman-stores), [Supercheap Auto](https://www.supercheapauto.com.au/customer-service/faq.html), [Auto One](https://www.autoone.com.au/pages/about-us).

## Dataset integrity

The original 12-photo pilot is retained unchanged. Its initial three-model run extracted all three fields correctly on 7 of 10 complete receipts. The first structural cache replay reached 10/10 complete receipts, with visible merchant 12/12, dates 10/10 and totals 11/11. This is development replay, not a new blind run, and has no new inference-time measurement.

An additional 27 development photos were annotated before inference: 20 complete and seven partial controls. One initially selected photo was excluded **before inference** because full-image inspection showed a reserved merchant group. Both the original 28-photo selection and its exclusion audit remain local. Original split labels were found wrong on several photos; the 173/49/54 split is provisional and must not be called proven merchant-disjoint. The reserved 49 photos have not been used for tuning.

Private first attempts, raw replies, image hashes, reference hashes, code hashes and subsequent replays are stored under `data/real-receipts/`; they are never committed.

## First visual results

On the new 27-photo set: merchant 22/25 under predeclared aliases (20/25 exact), date 22/24, visible total 25/25, and all three fields correct on 17/20 complete receipts. However, it also populated **both absent totals**, one absent date and both unknown merchant fields. Thus 25/25 visible totals alone is a misleading success criterion.

On the original 12-photo pilot: one schema failure (Australian date string instead of ISO), 9/10 complete receipts correct, and the missing-field controls were left empty. Date format normalization was subsequently added with regression tests; the original failed attempt remains unchanged.

The new visual run totaled 212.2 seconds for 27 images (median 8.0 seconds); the original-pilot visual run totaled 215.7 seconds for 12 images (median 19.0 seconds). Orientation was prepared beforehand; first receipt includes model loading. Concurrent OCR and unrelated local workloads make these **shared-workload observations**, not a fair isolated speed comparison or production latency promise.

## Outstanding errors and limitations

- A model can agree with OCR on text while misunderstanding its role. Subtotals, customer names, payment providers and warranty dates need semantic checks.
- Stylised logos can require a verified public identity source. Any result using that enrichment must remain separate from literal OCR accuracy claims.
- Handwritten totals may be legible to the image model but uncorroborated by OCR. Cropped documents cannot supply information outside the photo.
- Payment-provider versus selling-business identity needs a consistent product policy and independent annotation review; do not change reference answers just to match predictions.
- One OXR first attempt took about 320 seconds, generated repetitive unusable text and was excluded from voting. Model completion does not imply recognition completeness.
- Confidence remains an evidence ranking, not a calibrated probability. The experimental image route cannot yet justify wider automatic confirmation.

## Final expanded development comparison

| Route | Merchant (aliases / exact) | Visible date | Visible total | All three on complete receipts | Automatic / wrong automatic |
|---|---:|---:|---:|---:|---:|
| Three-model first attempt | 14/25 / 11/25 | 23/24 | 22/25 | 10/20 | 5 / 1 |
| Revised parser replay | 19/25 / 16/25 | 23/24 | 24/25 | 15/20 | 7 / 0 |
| Image review of every record, saved-output replay | 25/25 / 22/25 | 24/24 | 25/25 | 20/20 | 6 / 0 |
| Live policy: image review only for uncertain records, saved-output replay | 25/25 / 22/25 | 24/24 | 25/25 | 20/20 | 7 / 0 |

Merchant aliases were fixed before inference. The final route includes development-added parsing rules and a publicly verified ABN cache entry. It is not an untouched test. The 12-photo original-pilot replay retains 10/10 complete records and 4 automatic confirmations with no reference nonmatches. Combined, the **30 complete development receipts** match all three fields under this alias policy; this is not a new 100-photo acceptance result.

Missing-field controls remain separate: revised date 3/3 and total 2/2 correct abstentions; merchant 1/2. The remaining payment-provider/selling-business ambiguity is retained as a nonmatch, not erased by changing its annotation. Thus the full 39-photo task is not universally perfect. The 27-photo first attempt incorrectly auto-confirmed a zero closing balance; this error is fixed in the candidate. Seven correct automatic confirmations are too few to establish production precision.

The original expanded three-model run took 2,787.9 seconds (46.5 minutes), median 81.9 and nearest-rank P95 298.9 seconds. Replays have no new OCR runtime and cannot be presented as speed improvements. The existing full-engine batch used the old unbounded runner; the new 180-second budget was added after these long-tail observations.

## Live path and remaining release gates

Actual photo import now retains the OCR record, invokes the pinned local image model only for uncertain records, checks image hashes and OCR semantic evidence, and then recomputes confidence and automatic tags. User corrections and already supported receipts bypass the model. Every visual attempt is retained; the worker has a 90-second limit. Missing model files, timeouts and malformed responses preserve OCR evidence rather than fail the import. `SMARTOCR_VISUAL_REVIEW=0` disables this optional local step.

A fresh real single-receipt runtime smoke test exercised the actual worker and import helper in 21.67 seconds, recovered the merchant and retained review status without writing the app database; its local result is retained. All 206 Python regression tests and six Node tests passed. Batch accuracy above remains saved-output development replay, not a fresh end-to-end acceptance run. Next release gates are independent annotation audit, untouched evaluation, automatic-precision calibration and a measured end-to-end latency budget. Payment success, duplicate transactions and accounting treatment also need separate validation; a correct printed gross amount does not establish that a payment succeeded.
