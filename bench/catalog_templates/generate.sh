#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

if command -v uv >/dev/null 2>&1; then
  uv run cloth-store-templates --output-root bench/catalog_templates --repo-root .
else
  PYTHONPATH=src python -m cloth_store.catalog_templates \
    --output-root bench/catalog_templates \
    --repo-root .
fi
