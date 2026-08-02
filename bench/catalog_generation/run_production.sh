#!/usr/bin/env bash
# Run production catalog pipeline for a fixture range (sequential, idempotent).
# Usage: run_production.sh --from-fixture 13 --to-fixture 18 [--dry-run | --regenerate]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
UV="${CLOTH_STORE_UV:-/scratch4weeks/pg00807/bin/uv}"
LOG="${ROOT}/bench/catalog_generation/catalog_production_batch.log"

FROM_FIXTURE=""
TO_FIXTURE=""
DRY_RUN=""
REGENERATE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --from-fixture) FROM_FIXTURE="${2:-}"; shift 2 ;;
    --to-fixture) TO_FIXTURE="${2:-}"; shift 2 ;;
    --dry-run) DRY_RUN="--dry-run"; shift ;;
    --regenerate) REGENERATE="--regenerate"; shift ;;
    *) echo "unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "${FROM_FIXTURE}" || -z "${TO_FIXTURE}" ]]; then
  echo "usage: $0 --from-fixture N --to-fixture M [--dry-run | --regenerate]" >&2
  exit 1
fi

cd "${ROOT}"
echo "Catalog batch started $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "${LOG}"
echo "=== PIPELINE range ${FROM_FIXTURE}-${TO_FIXTURE} $(date -u +%H:%M:%S) ===" | tee -a "${LOG}"

"${UV}" sync --group dev --group gemini
"${UV}" run cloth-store-catalog-pipeline \
  --repo-root "${ROOT}" \
  --from-fixture "${FROM_FIXTURE}" \
  --to-fixture "${TO_FIXTURE}" \
  ${DRY_RUN} ${REGENERATE} 2>&1 | tee -a "${LOG}"

echo "Catalog batch done $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "${LOG}"
