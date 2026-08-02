#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SIF="${CLOTH_STORE_SIF:-$HOME/LlamaFactory/llamafactory_v3.sif}"
UV="${CLOTH_STORE_UV:-/scratch4weeks/pg00807/bin/uv}"
JSON_DIR="${ROOT}/bench/plan1_localization/outputs"
OUT_DIR="${ROOT}/bench/plan1_localization/outputs/masks"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mapfile -t FIXTURES < <("${SCRIPT_DIR}/resolve_fixtures.sh" "$@")

mkdir -p "${OUT_DIR}"

apptainer exec --nv "${SIF}" bash -lc "
  set -euo pipefail
  [[ -f \"\$HOME/.cache_env\" ]] && source \"\$HOME/.cache_env\"
  export HF_HOME=/scratch4weeks/pg00807/huggingface
  cd \"${ROOT}\"
  \"${UV}\" sync --group dev --group vlm --group sam
  \"${UV}\" run cloth-store-masks \\
    --output-dir \"${OUT_DIR}\" \\
    --batch-fixtures ${FIXTURES[*]} \\
    --repo-root \"${ROOT}\" \\
    --json-dir \"${JSON_DIR}\"
"

echo "Wrote masks under ${OUT_DIR}"
