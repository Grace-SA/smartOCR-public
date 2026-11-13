#!/bin/zsh
set -e
cd "${0:A:h}"
RUNTIME_PYTHON="${RECEIPT_PYTHON:-${HOME}/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3}"
if [[ ! -x "$RUNTIME_PYTHON" ]]; then
  RUNTIME_PYTHON="$(command -v python3)"
fi
mkdir -p .build
if [[ ! -x .build/vision_ocr || scripts/vision_ocr.swift -nt .build/vision_ocr ]]; then
  swiftc -module-cache-path .build/module-cache scripts/vision_ocr.swift -o .build/vision_ocr
fi
if [[ ! -x .build/local_ai || scripts/local_ai.swift -nt .build/local_ai ]]; then
  swiftc -parse-as-library -module-cache-path .build/module-cache scripts/local_ai.swift -o .build/local_ai
fi
exec "$RUNTIME_PYTHON" app.py
