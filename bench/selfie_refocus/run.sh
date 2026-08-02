#!/usr/bin/env bash
# Bench selfie crop/blur-only refocus and optional final_selfies packaging.
# Does not modify source photos or production catalog outputs.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SIF="${CLOTH_STORE_SIF:-$HOME/LlamaFactory/llamafactory_v3.sif}"
UV="${CLOTH_STORE_UV:-/scratch4weeks/pg00807/bin/uv}"
OUTPUT_ROOT="${ROOT}/bench/selfie_refocus/candidates"
FINAL_ROOT="${ROOT}/final_selfies"
JSON_DIR="${ROOT}/bench/plan1_localization/outputs"

FROM_FIXTURE=""
TO_FIXTURE=""
FIXTURES=()
REUSE_MASK=0
PACKAGE=1
VALIDATE_ONLY=0
FORCE=0

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
    --reuse-mask)
      REUSE_MASK=1
      shift
      ;;
    --package)
      PACKAGE=1
      shift
      ;;
    --bench-only)
      PACKAGE=0
      shift
      ;;
    --validate-only)
      VALIDATE_ONLY=1
      shift
      ;;
    --force)
      FORCE=1
      shift
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ ${#FIXTURES[@]} -eq 0 && -z "${FROM_FIXTURE}" ]]; then
  FROM_FIXTURE=1
  TO_FIXTURE=31
fi

ARGS=(--repo-root "${ROOT}" --output-root "${OUTPUT_ROOT}" --json-dir "${JSON_DIR}")
PKG_ARGS=(--repo-root "${ROOT}" --bench-root "${OUTPUT_ROOT}" --final-root "${FINAL_ROOT}" --json-dir "${JSON_DIR}")
if [[ ${#FIXTURES[@]} -gt 0 ]]; then
  for fixture in "${FIXTURES[@]}"; do
    ARGS+=(--fixture "${fixture}")
    PKG_ARGS+=(--fixture "${fixture}")
  done
else
  ARGS+=(--from-fixture "${FROM_FIXTURE}" --to-fixture "${TO_FIXTURE}")
  PKG_ARGS+=(--from-fixture "${FROM_FIXTURE}" --to-fixture "${TO_FIXTURE}")
fi
if [[ "${REUSE_MASK}" -eq 1 ]]; then
  ARGS+=(--reuse-mask)
fi
if [[ "${FORCE}" -eq 1 ]]; then
  ARGS+=(--force)
  PKG_ARGS+=(--force)
fi

if [[ "${VALIDATE_ONLY}" -eq 1 ]]; then
  apptainer exec "${SIF}" bash -lc "
    cd \"${ROOT}\"
    \"${UV}\" sync --group dev
    \"${UV}\" run cloth-store-selfie-final-packaging --validate-only \"\${@}\"
  " _ "${PKG_ARGS[@]}"
  exit 0
fi

apptainer exec --nv "${SIF}" bash -lc "
  [[ -f \"\$HOME/.cache_env\" ]] && source \"\$HOME/.cache_env\"
  export HF_HOME=/scratch4weeks/pg00807/huggingface
  cd \"${ROOT}\"
  \"${UV}\" sync --group dev --group sam --group vlm
  \"${UV}\" run cloth-store-selfie-refocus \"\${@}\"
" _ "${ARGS[@]}"

if [[ "${PACKAGE}" -eq 1 ]]; then
  apptainer exec "${SIF}" bash -lc "
    cd \"${ROOT}\"
    \"${UV}\" sync --group dev
    \"${UV}\" run cloth-store-selfie-final-packaging \"\${@}\"
  " _ "${PKG_ARGS[@]}"
fi

echo "bench outputs: ${OUTPUT_ROOT}"
echo "final deliverable: ${FINAL_ROOT}"
echo "privacy crop (optional): uv run cloth-store-selfie-privacy-crop --repo-root . --from-fixture 1 --to-fixture 31"
