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

### Current blockers

- GitHub connector cannot create repositories. Browser sign-in is required for the authorized private repository creation; local work continues independently.

### Recording protocol

Every experiment records input and code hashes, model settings, cache/cold-start status, hardware, per-image wall time, output availability, field scores and failures. Preserve first attempts. Mark whether references were checked by a person, by an assistant, or remain unverified. Never change a holdout reference merely to match a prediction. Keep identifying receipt content out of this journal.
