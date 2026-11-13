# Receipt structure and evaluation protocol

Real photos are private. Examples below describe structural patterns without reproducing identifying receipt details.

## What the first visual audit established

- A document title can precede the business name. Restricting merchant candidates to the first line or the largest font misses readable business names.
- A payment slip can sit beside a merchant invoice in the same photo. Global line sorting interleaves two columns, so a bank name may precede the supplier's logo. Determine document boundaries and reading order before selecting roles.
- A terminal can print amount, currency and SALE on separate lines or in a different OCR order. The amount is present but a nearby-label regex can still miss it.
- “Total includes tax” describes the tax component, whereas “Total incl. tax” may label the final amount. The entire phrase and neighbouring amounts matter.
- A receipt may display a trading brand, legal entity, outlet, address and payment provider. Retain these as separate concepts. Display merchant matching and exact legal-name matching are different metrics.
- Card expiry is not the transaction date. A photograph with the bottom cropped may genuinely have no transaction date.
- Several photos can cover one long receipt, and one photo can contain several receipts. Neither photo count nor file hash proves transaction count. A payment stub attached to an invoice usually corroborates that invoice rather than adding a second expense.
- An invoice's amount due is a document total, not proof it was paid. A handwritten customer's company name is not necessarily the supplier.
- Savings, loyalty points, tax, change, balance due and payment are separate roles. Do not fill a missing final total with an arbitrary visible amount.

## Local dataset status

The supplied ZIP has 276 decodable images, 276 distinct pixel hashes and four perceptual-similarity candidate pairs. Pixel uniqueness does not establish distinct transactions. Thumbnail review also identified potentially repeated invoices and partial photographs.

Initial partition: 173 development images, 49 held-out images grouped by merchant/template, 54 quarantined for document boundaries, partial images, exposed card data, non-Australian material or unresolved grouping. Quarantine does not mean rejection; those images require explicit task definitions before aggregate accuracy scoring.

Holdout images were seen only as thumbnails for grouping. They have not been inferred or fully transcribed. This is a model-unseen grouped holdout, not a claim that the developer has never seen any pixels. Some brands were already known from earlier public datasets; it tests new photos and template groups, not brand-unseen generalisation.

The first 12-image pilot is deliberately selected development material. It includes two incomplete-document controls from quarantine; these are used only to measure abstention. Ten images have all three visible reference fields. An assistant initially misread one amount in a downscaled preview. The original reference and evaluation were retained; a native-resolution crop showing the same amount in subtotal, total and EFT supports a logged reference revision. All references remain assistant annotations, not independent human gold.

## Experiment rules

1. Preserve originals, checksums, source-to-preview mappings and initial predictions. Do not overwrite an experiment folder.
2. Inference manifests contain image IDs and paths only. Reference annotations are read exclusively by the scorer.
3. Freeze merchant aliases before inference. Report strict matches and separately accepted aliases.
4. Report accuracy on visible fields with explicit denominators. Missing-reference fields are abstention controls, not successful extraction.
5. Keep automatic-confirmation coverage and false-confirmation counts alongside accuracy. Returning everything as review is not a completed automatic workflow.
6. Record preprocessing, startup, inference, semantic interpretation and classification. Distinguish a same-image cache hit from warm inference on a new image.
7. Grounded AI output must cite exact OCR evidence. This prevents unsupported values but does not prove that a cited number or name has the correct role.
8. Keep experimental routes out of the live app until generalisation and confirmation errors have been evaluated. The three-engine live route remains the default.

## Remaining work

Document segmentation and stitching, transaction-level duplicate detection, a larger checked reference set, visually grounded logo interpretation, and calibrated automatic confirmation remain necessary. The current fast AI experiment is text-based Apple Foundation Models after Paddle, not a vision-language replacement.
