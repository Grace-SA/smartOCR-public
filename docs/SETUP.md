# Running this prototype

The repository contains source, synthetic test fixtures and engineering documentation. It deliberately excludes real receipts, public research datasets, model weights, caches, screenshots and generated reports. A fresh checkout starts without receipt records. Historical dataset-driven scripts need their separately retained local research files.

## Base workspace

Use Python 3.11 or newer and install `requirements.txt`. Run `python3 app.py`, then open `http://127.0.0.1:8765`. `RECEIPT_PORT` changes the port; `RECEIPT_DATA_FILE` selects a separate local JSON database. The server accepts local loopback requests only. Base filtering and CSV/JSON/PDF exports do not need a hosted AI account.

## Local OCR dependencies

The current verified installation is Apple Silicon macOS. `ocr_ensemble.py` uses a sibling `pdf-to-ppt/ocr` project for verified Paddle ONNX/orientation adapters and a sibling `ocr-mac-test` for the MLX U2/OXR environments, model weights and pinned OXR source. These adapters, manifests and weights are not bundled or installed by `requirements.txt`. OXR additionally needs the existing loopback layout detector at port 18081. Do not stop another project's detector service.

This dependency arrangement is a known portability limitation, not a production installer. Provisioning self-contained model adapters and versioned weights is a subsequent deployment task.

## Optional local AI and Excel export

`start.command` builds the Swift Vision and Foundation Models helpers. Apple Foundation Models requires a compatible Mac and enabled/available Apple Intelligence; unavailable AI must leave deterministic statistics usable. The launcher accepts `RECEIPT_PYTHON`, otherwise uses the installed local runtime or `python3`.

Excel export uses the existing Node `@oai/artifact-tool` renderer through `scripts/export_workbook.mjs` and the installed runtime. This package is not provisioned by the Python requirements. Link `scripts/node_modules` to the installed runtime's `node/node_modules` directory (or provision the package in your own environment); the link is ignored by Git. `RECEIPT_NODE` selects the Node executable. CSV remains readable by spreadsheet software when that renderer is unavailable.

## Private experiments

```sh
python3 scripts/inventory_receipts.py /path/to/receipts.zip --out data/real-receipts
python3 scripts/benchmark_receipts.py --manifest data/real-receipts/pilot-manifest.json --out data/real-receipts/experiments/new-baseline --route ensemble
SMARTOCR_RESIDENT=1 python3 scripts/benchmark_receipts.py --manifest data/real-receipts/pilot-manifest.json --out data/real-receipts/experiments/new-resident --route resident
swiftc -parse-as-library -module-cache-path .build/module-cache scripts/receipt_semantics.swift -o .build/receipt_semantics
SMARTOCR_RESIDENT=1 python3 scripts/benchmark_receipts.py --manifest data/real-receipts/pilot-manifest.json --out data/real-receipts/experiments/new-quick --route quick-ai
python3 scripts/score_receipt_experiment.py data/real-receipts/experiments/new-baseline --reference data/real-receipts/pilot-reference-v2.json
```

These commands require locally prepared manifests and references. Run comparison routes sequentially to avoid competing model workloads. `SMARTOCR_RESIDENT=1` is experimental and disabled by default. Its worker retains Paddle/orientation and U2 models; OXR still uses its original adapter. Workers use private pipes, bounded waits and owned-process cleanup.

The quick route requires the separately compiled receipt-semantics helper. It uses Foundation Models' runtime generation schema so it builds with Command Line Tools without Xcode's macro plugin. Structured JSON does not guarantee correct facts: Python validates citations independently, stores rejected suggestions for local audit and keeps every quick-route receipt in review. See Apple's [guided generation documentation](https://developer.apple.com/documentation/foundationmodels/generating-swift-data-structures-with-guided-generation). No receipt is sent to a hosted model by this route.

## Checks

```sh
python3 -m unittest discover -s tests -q
node --check static/app.js
```

Network-listening API tests need loopback permission. Model benchmarks need the local model environments and Metal access. Browser checks must use an isolated test database for writes; preserve user overrides in the real workspace.
