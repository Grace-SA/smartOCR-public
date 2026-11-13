# Local receipt model tuning: preparation, not a trained result

## Current decision

The next experiment should compare the pinned base image model with a small supervised adapter, rather than add more receipt-specific brand exceptions and call that model training. Keep the existing OCR and evidence checks as the baseline. A candidate is better only if untouched data shows a useful gain without more invented fields or false automatic confirmations.

No weights were trained in this revision. The original Mac, its 276 private photos, annotations, cached first attempts and model runtime are unavailable from the current environment. Main at `c628365` reports 30/30 complete development receipts matching three fields in tuned cache replay, but an unresolved missing-merchant control and no completed 49-image reserved evaluation. Those observations cannot demonstrate independent 100% accuracy. The provisional 173/49/54 split has known group-label errors; do not reuse it as proven independent data.

## Prepare a defensible dataset

1. Preserve source images, the old blind100 freeze, first attempts, reference revisions and the live database. Keep the 49 reserved images out of training and hyperparameter selection. If group leakage is discovered, document it without silently moving images or rewriting old results; rebuild a new untouched test set before any generalisation claim.
2. Visually audit transaction, merchant and template groups, including near-duplicate/cropped photos. Exact bytes and decoded pixels do not detect every repeated transaction. Use the existing inventory's near-duplicate candidates as review aids, not an automatic grouping decision.
3. Have a person independently verify merchant/date/gross-total labels and their printed evidence. Distinguish absent/cropped/unreadable values from model failures. A human review flag is an attestation, not a label the software can manufacture. Never copy an unverified model prediction into the target answer.
4. Select train and validation groups only from the audited development pool. Include refund, tax/subtotal, terminal-payment, partial-document and missing-field controls. Keep validation examples out of training. Human corrections are authoritative, but do not alter a frozen reference just to match a candidate.
5. Store the new manifest under ignored `data/` or `private/`. Each record needs `id`, `split`, `local_path`, original `sha256`, `merchant_group`, `template_group`, `transaction_group`, and `group_review: human_verified`. Valid splits are `train`, `validation`, `holdout`, `quarantine`. Use local opaque group identifiers, not customer data. Group audit must genuinely establish independence; making up a distinct identifier per image defeats the purpose.
6. Train/validation records also need `label_review: human_verified`, a `labels` object and an `evidence` object, each with exactly `merchant`, `date`, `total`. A missing value and its evidence are both null. Dates are ISO strings; totals are signed decimal strings with two places. Evidence is the exact printed support. Holdout records must not include labels or evidence; keep those in an evaluator-only file.

Run the deterministic local preparation:

```sh
python scripts/prepare_receipt_training.py \
  --manifest data/real-receipts/audited-training-manifest.json \
  --out data/training/preparation-001
```

The command checks every source hash, decoded-image duplicates, cross-split merchant/template/transaction groups and reviewed labels. It requires nonempty train/validation/holdout and missing-field controls in both train and validation. It never silently fixes data or overwrites an existing run. Outputs are private `train.jsonl`, `validation.jsonl` and fingerprint metadata; it does not export test answers, run a trainer, contact a network service or modify the application.

This is a **generic SFT staging schema**, not a verified MLX trainer dataset. Image paths are local and remain mutable. Before any trainer runs, recheck source hashes, dataset export hashes and the model revision. Copy/freeze run inputs locally if needed. A model-specific adapter must correctly insert image tokens and mask loss to assistant targets; smoke-test decoding and a forward/backward step before a real run. Do not point a trainer at the entire private data directory or evaluator labels. No private data, output JSONL, adapters or weights should be committed to GitHub.

## Candidate experiment, to execute on the original Mac

- Baseline A: current pinned `mlx-community/Qwen3-VL-8B-Instruct-4bit` at revision `defcdea7cc7a4b0858fea563cbbce171d328e457`, unchanged prompt and evidence reconciliation. Record both fresh image inference and end-to-end OCR timings.
- Candidate B: image-model supervised LoRA adapter on the audited training pool. Start with language-layer adapters while retaining the base vision encoder. A rank-8, batch-1, small-learning-rate trial is an experiment, not a tuned recommendation or proven compatible configuration. Verify training support for the installed runtime/model first; do not silently upgrade the working inference environment.
- Use a separate training environment and pin package/model revisions. Upstream [MLX-VLM training documentation](https://github.com/Neywa-Labs/mlx-vlm/blob/main/docs/training.md) describes local SFT/LoRA and assistant-completion supervision; its current API differs from older releases. Select a compatible pinned version after a local smoke test. This revision does not claim that the existing MLX-VLM 0.7.12 runtime has passed a training test.
- Compare validation results across a small predeclared search, for example ranks 8/16 and learning rates 1e-5/5e-5, at fixed seeds and equal epoch budgets. These values are starting hypotheses, not results. Select by extraction and abstention metrics, not training loss alone. Stop a trial when validation worsens or outputs become repetitive/malformed. Record GPU/Metal memory and wall time rather than estimating them from replay.
- Keep all inference offline. Disable telemetry, experiment uploads and automatic Hub pushes. Loading a model must not send receipt data to a cloud API. Preserve reference-free inference manifests and original raw model responses, including failures.

## Acceptance and reporting

Freeze one candidate and its hashes before the first reserved-set evaluation. Compare the same input records against the baseline; failed and unprocessed cases stay in the denominator. Record merchant exact and predeclared-alias scores separately, date/total exact match, three-field record match, absent-field hallucinations, schema failures, false automatic confirmations, automatic coverage, per-category counts and median/P95 latency. Do not count an abstention as correct extraction or a successful JSON parse as an accurate receipt.

All three fields and controls matter: a gain on complete receipts cannot excuse invented totals on cropped photos. Do not lower confidence thresholds to improve apparent coverage. Even 49/49 correct on a genuinely untouched set would be a small-sample result, not a universal guarantee; report sample counts and uncertainty. Do not repeatedly tune on the reserved set. Keep the adapter experimental and review-only until independent audit, fresh inference, end-to-end evaluation and regression checks pass.

## This revision's verification scope

Only synthetic preparation tests can run here. They cover split leakage, duplicates, image hashes, reviewed-label/evidence schema, missing controls, immutable outputs and private-path confinement. They do not measure OCR accuracy, train an adapter, independently audit real labels, validate model-specific preprocessing or prove production readiness. The actual training and model comparison remain blocked on access to the original Mac/data/runtime.

Verification on the complete source snapshot: 13 new preparation tests and syntax checks pass. Independent review fixed a byte-consistency bug by decoding the exact bytes whose original SHA was verified, rather than reopening a possibly changed file. Full Python discovery ran 219 tests: 209 passed and 10 errored because of two unavailable private-image fixtures and eight font/Excel-renderer dependencies. All 11 Node tests passed. These environment errors remain unresolved and are not counted as passing. No real model training or inference was performed.
