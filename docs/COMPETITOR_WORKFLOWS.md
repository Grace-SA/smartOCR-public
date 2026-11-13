# Receipt workflow research and interaction decisions

Reviewed 13 November 2026 using Australian App Store listings and official help. This is a documented workflow review, not a hands-on trial of paid native apps. App Store reviews are individual historical reports, not prevalence estimates or verified current defects. Similar names were checked against developers: Smart Receipts by Reactive Apps, Expensify by Expensify Inc., Dext by Dext Software. The similarly named “Receipt Organizer: Expensify” is not the Expensify benchmark.

## Findings

| Product | Documented workflow | Relevant lesson for smartOCR |
|---|---|---|
| Smart Receipts | Receipt entries → organise into reports → export/share. Bottom tabs separate receipts, distances, reports and share; receipts can be sorted by report, category and date. | Reports need a visible scope and a clear destination. For this MVP, filtered results can become a report without first creating a folder. |
| Expensify | SmartScan fills merchant, date and amount. Failed or incorrect scans have an explicit troubleshooting/correction path. The broader product includes chat, reimbursement and business workspaces. | Show processing and completion explicitly. Surface uncertain fields, preserve manual correction, and keep the MVP focused on personal receipt organisation. |
| Dext | Single captures one document; Multiple creates separate documents from up to 50 photos; Combine makes one document from multiple photos. Review allows retake, rotate, crop and full-size inspection. | “Several photos” and “several transactions” are different. Never silently merge receipts or treat a multi-receipt photo as one transaction. |

Sources: [Smart Receipts workflow](https://help.smartreceipts.co/en/articles/15483971-about-smart-receipts), [Expensify scan corrections](https://help.expensify.com/articles/new-expensify/reports-and-expenses/Troubleshoot-SmartScan-Issues), [Dext capture modes](https://help.dext.com/en/articles/105670-how-to-scan-and-upload-documents-in-the-dext-mobile-app).

## Australian listing signals

- A September 2023 Smart Receipts review praised tax-time organisation but wanted to zoom before accepting a photo. Another asked for cross-device synchronisation. These are useful task signals; they do not establish today's feature gaps. [AU listing](https://apps.apple.com/au/app/smart-receipts-expenses-tax/id905698613)
- A July 2018 Expensify review described difficulty finding the reporting action after scanning. It is old, so use it as an interaction failure to test against, not evidence of the current app's quality. [AU listing](https://apps.apple.com/au/app/expensify-travel-expense/id471713959)
- Dext's listing includes positive accounts of bulk administration and duplicate detection. Its “99.9%” extraction language is a vendor claim with no comparable test protocol here; it is not a benchmark result for our photos. [AU listing](https://apps.apple.com/au/app/dext-receipt-scanner/id418327708)

## Concrete design decisions

1. Open to all organised receipts, with a single visible exception-review action. A pile of mandatory forms must not be the first impression.
2. Separate scan state from receipt correctness. Processing, extracted, needs review and user override have distinct meanings. An evidence index is never displayed as an accuracy probability.
3. Keep merchant/date/amount and relevant warnings prominent in the detail view. Put optional metadata and technical evidence behind disclosure controls. Offer save-and-next for a review session.
4. Let the photo zoom inside the review view. Do not draw evidence boxes unless the saved geometry maps to the displayed original image.
5. Preview each export: selection scope, date coverage, per-currency totals, number of unreviewed/incomplete records, chosen format and included columns. Generate from the previewed IDs; flag changes to that snapshot.
6. Describe ordinary PDF exports as statistics plus receipt information. Preserve original images locally; do not imply they are embedded.
7. Keep categories and date/refund tags automatic and editable. Work/personal purpose needs context and is optional; a merchant alone cannot establish it.
8. Show a useful computed report even if AI is unavailable. Every AI statement must use the same selected receipt snapshot.

## Acceptance tasks

- Import a batch, see progress and completed records without waiting for all images.
- Open the exception queue, identify the uncertain field, inspect the photo, correct it and advance.
- Filter by period and category, preview the selected totals and export matching Excel/PDF/CSV/JSON.
- Override an automatic result and inspect the preserved original/history.
- Complete the same tasks at a narrow mobile width with keyboard-accessible controls.

Deferred: native automatic capture, multi-document segmentation/stitching, accounts, email ingestion, cloud sync, reimbursement approvals and subscription flows. A prototype cannot imply these already work.
