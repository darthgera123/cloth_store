#!/usr/bin/env bash
# Extract structured VLM garment attributes for a fixture range.
# Usage: run_vlm_attributes.sh --from-fixture 13 --to-fixture 18
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SIF="${CLOTH_STORE_SIF:-$HOME/LlamaFactory/llamafactory_v3.sif}"
UV="${CLOTH_STORE_UV:-/scratch4weeks/pg00807/bin/uv}"
VLM_DIR="${ROOT}/bench/catalog_generation/vlm_attributes"
CUTOUT_ROOT="${ROOT}/bench/plan1_localization/outputs/catalog_cutouts"
LOG="${ROOT}/bench/catalog_generation/vlm_extraction_batch.log"
PLAN1_SCRIPT="${ROOT}/bench/plan1_localization/resolve_fixtures.sh"

FROM_FIXTURE=""
TO_FIXTURE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --from-fixture) FROM_FIXTURE="${2:-}"; shift 2 ;;
    --to-fixture) TO_FIXTURE="${2:-}"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "${FROM_FIXTURE}" || -z "${TO_FIXTURE}" ]]; then
  echo "usage: $0 --from-fixture N --to-fixture M" >&2
  exit 1
fi

mapfile -t FIXTURES < <("${PLAN1_SCRIPT}" --from-fixture "${FROM_FIXTURE}" --to-fixture "${TO_FIXTURE}")
mkdir -p "${VLM_DIR}"
echo "VLM batch started $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "${LOG}"

for id in "${FIXTURES[@]}"; do
  for role in top bottom; do
    OUT="${VLM_DIR}/${id}_${role}.attributes.json"
    if [[ -f "${OUT}" ]]; then
      echo "SKIP ${id}/${role} (exists)" | tee -a "${LOG}"
      continue
    fi
    CUTOUT="${CUTOUT_ROOT}/${id}/catalog_${role}.png"
    if [[ ! -f "${CUTOUT}" ]]; then
      echo "SKIP ${id}/${role} (missing cutout)" | tee -a "${LOG}"
      continue
    fi
    echo "=== EXTRACT ${id}/${role} $(date -u +%H:%M:%S) ===" | tee -a "${LOG}"
    SOURCE=$("${UV}" run python -c "
from cloth_store.catalog_paths import resolve_fixture_source_path
print(resolve_fixture_source_path('${id}', repo_root='${ROOT}'))
")
    apptainer exec --nv "${SIF}" bash -lc "
      set -euo pipefail
      [[ -f \"\$HOME/.cache_env\" ]] && source \"\$HOME/.cache_env\"
      export HF_HOME=/scratch4weeks/pg00807/huggingface
      cd \"${ROOT}\"
      \"${UV}\" sync --group dev --group vlm
      \"${UV}\" run cloth-store-vlm-garment-attributes \\
        \"${CUTOUT}\" \\
        --output \"${OUT}\" \\
        --fixture \"${id}\" \\
        --role \"${role}\" \\
        --source-photo \"${SOURCE}\"
    " 2>&1 | tee -a "${LOG}"
  done
done

echo "VLM batch done $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "${LOG}"
