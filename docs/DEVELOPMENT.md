# smartOCR development record

This is the versioned engineering journal. Product copy is English. Real receipt images, annotations and OCR output remain local and are excluded from Git. Each milestone records changes, validation, problems and next steps. A measured sample result is not a population accuracy claim.

## 2026-11-13 Baseline before real receipt development

### Completed

- Local browser workflow: photo import, three OCR engines, evidence reconciliation, confidence routing, override history, automatic categories/tags, filters, scoped Excel/PDF/CSV/JSON exports and grounded optional AI commentary.
- Normal PDF exports contain statistics and a receipt register; original photos are not embedded.
- Existing workspace contains 100 development receipts. Current confirmation counts: 69 automatic, 30 review, one user-confirmed. User corrections must survive all subsequent development.
- Historical verification recorded 158 Python tests, six Node tests, API and browser workflow checks passing. These are previous checks, not newly rerun checks for later revisions.

### Evidence and limitations

- Frozen independent 100-image run: strict merchant 11%, date 86%, total 65%, all three 7%. Reference annotations were assistant visual readings, not independent human gold; 73% of samples were transport.
- Automatic coverage was 4%. Three strict merchant nonmatches were printed legal-name suffixes absent from references; these are not proven wrong merchant identities.
- Total wall time 7,430.67 seconds; median 58.83, P95 155.36. Shared local hardware and repeated process/model loading limit transferability.
- One known slow image improved from 474.95 to 22.18 seconds after disabling expensive retries, but its amount remained unavailable. This is not an accuracy improvement or representative speed benchmark.
- Current inference depends on sibling project model environments, Mac-specific runtime paths and a local OXR layout service.

### Approved next work

1. Preserve the baseline in a private GitHub repository, `Grace-SA/smartOCR`.
2. Inventory the supplied 276-image archive locally. Deduplicate and separate development/reference work from an untouched grouped holdout.
3. Compare full ensemble, adaptive OCR and visual AI approaches with identical inputs and explicit timing boundaries.
4. Research Smart Receipts, Expensify and Dext; improve capture, exception review and scoped report interaction.
5. Validate extraction, automatic-confirmation errors, coverage, speed and the end-to-end workflow together.

### Blocker at baseline (resolved)

- GitHub connector could not create repositories. After browser sign-in, the authorized private repository was created and baseline commit `4aece3b` pushed over HTTPS. Remote privacy was verified. No receipt images, annotations, generated reports or credentials were committed.

### Recording protocol

Every experiment records input and code hashes, model settings, cache/cold-start status, hardware, per-image wall time, output availability, field scores and failures. Preserve first attempts. Mark whether references were checked by a person, by an assistant, or remain unverified. Never change a holdout reference merely to match a prediction. Keep identifying receipt content out of this journal.

## 2026-11-13 Real-photo pilot and workflow revision

### Completed and verified

- Decoded and fingerprinted all 276 supplied photographs; retained original bytes locally. Reviewed contact sheets and froze an initial merchant/template grouping: 173 development, 49 held out, 54 quarantined. File uniqueness is not transaction uniqueness.
- Created a 12-image development pilot and separate image-only inference manifest. The ten complete references and two partial controls were visually read before inference. One initially misread amount was corrected only after native-resolution image inspection; both reference versions, the first evaluation and a revision journal remain preserved locally.
- Ran the same pilot through the original ensemble, resident ensemble, unstructured quick AI and structured quick AI. Saved first attempts, wall times and code/input hashes. The scorer never feeds reference values into OCR.
- Added optional owned-process residency, an isolated experimental single-Paddle route and constrained local AI generation with independently checked source citations. All quick results require review. Available model output and validated suggestions are distinct states.
- Studied official competitor workflows and Australian listings; applied the findings to English All receipts entry, focused review, photo zoom, save-and-next, collapsed optional fields and export preview.
- Added export snapshot validation: altered data after preview returns HTTP 409 rather than silently exporting a different record set. Actual filtered JSON, Excel and PDF browser exports were exercised using a separate synthetic database.
- Verified synthetic amount correction preserves the original value and edit history. Main workspace receipt file remains byte-for-byte unchanged during QA.
- End-to-end report testing exposed a false count written in words: one human-confirmed receipt was described as both an automatic and a human confirmation. Replaced unconstrained AI prose with validated selection/prioritisation of applicable action IDs; the app renders predefined evidence-based guidance and computes all factual statements. A real local-AI rerun returned valid actions on its first attempt. Historical free-form sample commentary is marked stale rather than silently trusted.
- Latest verification: 171 Python tests, six Node tests and JavaScript syntax check passed; desktop and 390px mobile layout checked. Evidence screenshots and run logs are retained locally, excluded from Git.

### Findings and decisions

- Residency alone: 406.1s versus 405.6s, identical merchant/date/total values on this pilot. Do not enable it as a claimed speed improvement.
- Initial quick AI: 74.5s, but all model field objects failed schema validation. This exposed a real integration failure, not successful AI interpretation; the failed experiment was preserved.
- Structured quick AI: 86.2s, all responses parse and each has some grounded evidence, but 14 field suggestions fail source-citation validation. Merchant selection remains weak. Five of ten complete records match all three fields, versus seven with the ensemble. Keep the fast route experimental.
- Structured generation first failed to compile because Command Line Tools lacks the Foundation Models macro plugin. Runtime schemas compile successfully and preserve the same field contract without requiring full Xcode.
- Correct citations prove that text exists, not that it is the merchant or final amount. A text-only model cannot recover an unread logo. A fast parser cannot justify automatic confirmation solely from its own confidence.
- Reports currently provide computed scope analysis and AI-prioritised workflow guidance. They do not yet provide reliable open-ended personal spending interpretation. Regression tests reject fabricated prose, inapplicable actions, duplicate IDs and extra output keys.

### Next stage / open problems

1. Address document segmentation, multi-column reading order and merchant/logo interpretation; handle final amount roles separately from payment/tax/change.
2. Independently check a larger development reference set and define transaction duplicates/multi-photo documents before scoring the quarantined images.
3. Compare a visually grounded correction route, retaining field evidence and manual overrides; no cloud upload has been enabled.
4. Freeze a candidate before first-attempt inference on the 49 grouped holdout images. Report field accuracy, automatic coverage, false confirmations and latency together; do not tune on that holdout.
5. Remove sibling-project/runtime coupling before distribution. Native camera/email/account/sync features remain outside this local verification milestone.

See [phase summary](PHASE_SUMMARY.md), [receipt structure notes](RECEIPT_STRUCTURE.md), [competitor workflow research](COMPETITOR_WORKFLOWS.md) and [setup](SETUP.md).
