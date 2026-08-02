#!/usr/bin/env bash
# Bench-only selfie crop/refocus review for selected fixtures.
# Does not modify source photos or production catalog outputs.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SIF="${CLOTH_STORE_SIF:-$HOME/LlamaFactory/llamafactory_v3.sif}"
UV="${CLOTH_STORE_UV:-/scratch4weeks/pg00807/bin/uv}"
OUTPUT_ROOT="${ROOT}/bench/selfie_refocus/candidates"
JSON_DIR="${ROOT}/bench/plan1_localization/outputs"

FROM_FIXTURE=""
TO_FIXTURE=""
FIXTURES=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --from-fixture)
      FROM_FIXTURE="${2:-}"
      shift 2
      ;;
    --to-fixture)
      TO_FIXTURE="${2:-}"
      shift 2
      ;;
    --fixture)
      FIXTURES+=("${2:-}")
      shift 2
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ ${#FIXTURES[@]} -eq 0 && -z "${FROM_FIXTURE}" ]]; then
  FROM_FIXTURE=1
  TO_FIXTURE=2
fi

ARGS=(--repo-root "${ROOT}" --output-root "${OUTPUT_ROOT}" --json-dir "${JSON_DIR}")
if [[ ${#FIXTURES[@]} -gt 0 ]]; then
  for fixture in "${FIXTURES[@]}"; do
    ARGS+=(--fixture "${fixture}")
  done
else
  ARGS+=(--from-fixture "${FROM_FIXTURE}" --to-fixture "${TO_FIXTURE}")
fi

apptainer exec --nv "${SIF}" bash -lc "
  [[ -f \"\$HOME/.cache_env\" ]] && source \"\$HOME/.cache_env\"
  export HF_HOME=/scratch4weeks/pg00807/huggingface
  cd \"${ROOT}\"
  \"${UV}\" sync --group dev --group sam
  \"${UV}\" run cloth-store-selfie-refocus \"\${@}\"
" _ "${ARGS[@]}"

echo "outputs: ${OUTPUT_ROOT}"
