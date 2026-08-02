#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SIF="${CLOTH_STORE_SIF:-$HOME/LlamaFactory/llamafactory_v3.sif}"
UV="${CLOTH_STORE_UV:-/scratch4weeks/pg00807/bin/uv}"
JSON_DIR="${ROOT}/bench/plan1_localization/outputs"
MASK_ROOT="${ROOT}/bench/plan1_localization/outputs/masks"
OUT_DIR="${ROOT}/bench/plan1_localization/outputs/catalog_cutouts"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mapfile -t FIXTURES < <("${SCRIPT_DIR}/resolve_fixtures.sh" "$@")

mkdir -p "${OUT_DIR}"

apptainer exec "${SIF}" bash -lc "
  set -euo pipefail
  [[ -f \"\$HOME/.cache_env\" ]] && source \"\$HOME/.cache_env\"
  cd \"${ROOT}\"
  \"${UV}\" sync --group dev
  \"${UV}\" run cloth-store-cutouts \\
    --output-dir \"${OUT_DIR}\" \\
    --batch-fixtures ${FIXTURES[*]} \\
    --repo-root \"${ROOT}\" \\
    --json-dir \"${JSON_DIR}\" \\
    --mask-root \"${MASK_ROOT}\"
"

echo "Wrote catalog cutouts under ${OUT_DIR}"
