# OCR parsing and training-preparation combination review

## Exact inputs and scope

- Main: `c628365fe9807e372db3275b8d95def334a991c1`.
- Draft PR #1: `2503d73d82baf64debbacc098139843c30021103`, whose original base is `c3bef91d606ad07073fbf99c86a81a91b4b527e0`.
- Draft PR #2: `efee3a2f4f7e5f4ed1bcd9aa2c12a42d6e96143a`, plus this revision's holdout-exposure declaration.

An isolated source copy applied PR #1's changes by a three-way file merge onto main plus PR #2. All six modified files combined without text conflicts; three PR #1 files were new. This was a local compatibility test, **not a GitHub merge, main update, release or deployment**. PR #2 remains training-preparation work; it does not silently incorporate PR #1's runtime parser changes.

## Results

- Combined Python discovery: **232 tests, 224 passed, eight environment errors**. All 14 training-preparation tests pass. The eight errors remain in font/Excel export tests because the configured font and renderer are unavailable; they are not counted as passing or disabled.
- Combined Node tests: **11 passed**.
- PR #2 without PR #1: **220 Python tests, 210 passed, ten environment errors**. The two additional errors are parser tests depending on a missing private-image fixture; PR #1 removes that unnecessary dependency.
- No synthetic assertion regression was observed in the tested combination. Clean textual combination and these tests do not establish correct real OCR behaviour, model accuracy, export correctness or deployment readiness.
- No private receipt data was available or uploaded. No model inference, adapter training, live database writes or real-image holdout evaluation ran.

## Holdout audit correction

The 49 reserved photos were previously viewed as thumbnails during grouping. They must be described as **reserved with prior thumbnail exposure**, not fully unseen. Their provisional grouping also contains known errors. This is not evidence that they were used for training, but it prevents an unqualified claim of an independent untouched blind test. Preserve the exposure history, inspect grouping without using reference outcomes to tune, and obtain a separate unexposed set for strong final generalisation claims.

Training preparation now requires a declared exposure category for every holdout image, preserves its aggregate count, and always reports `unseen_holdout_verified: false`. The tool cannot determine whether a review attestation is truthful or detect every crop/transaction duplicate. Private labels, near-duplicate review and group independence still require audit on the original Mac.

## Before any integration decision

1. Recheck current main and both PR heads; this report applies only to the commits above and the documented exposure change.
2. Run the complete environment-dependent suite and real model/receipt regression on the original host. Do not reuse historical passed tests as a pass for this combination.
3. Keep frozen historical scores unchanged; compare any new scoring protocol on a newly recorded run with explicit denominators and reference provenance.
4. Keep manual confirmation authoritative and changed visual-model suggestions review-only. No expanded automatic-confirmation policy was approved or tested here.

The remaining release blocker is evidence, not a merge conflict: real-data grouping/annotation audit, fresh inference, missing-field controls, automatic-confirmation calibration and timing still have not been verified for the combined candidate.
