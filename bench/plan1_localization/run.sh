#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SIF="${CLOTH_STORE_SIF:-$HOME/LlamaFactory/llamafactory_v3.sif}"
UV="${CLOTH_STORE_UV:-/scratch4weeks/pg00807/bin/uv}"
OUT_DIR="${ROOT}/bench/plan1_localization/outputs"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mapfile -t FIXTURES < <("${SCRIPT_DIR}/resolve_fixtures.sh" "$@")

mkdir -p "${OUT_DIR}"

apptainer exec --nv "${SIF}" bash -lc "
  set -euo pipefail
  [[ -f \"\$HOME/.cache_env\" ]] && source \"\$HOME/.cache_env\"
  export HF_HOME=/scratch4weeks/pg00807/huggingface
  cd \"${ROOT}\"
  \"${UV}\" sync --group dev --group vlm
  for id in ${FIXTURES[*]}; do
    OUT=\"${OUT_DIR}/\${id}.json\"
    if [[ -f \"\${OUT}\" ]]; then
      echo \"SKIP \${id} (bbox exists)\"
      continue
    fi
    IMAGE=\$(\"${UV}\" run python -c \"
from cloth_store.catalog_paths import resolve_fixture_source_path
print(resolve_fixture_source_path('\${id}', repo_root='${ROOT}'))
\")
    \"${UV}\" run cloth-store-bbox \"\${IMAGE}\" --output \"\${OUT}\"
  done
"

echo "Wrote outputs under ${OUT_DIR}"
