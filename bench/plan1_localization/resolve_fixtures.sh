#!/usr/bin/env bash
# Shared fixture selection for Plan 1 batch scripts.
# Usage: resolve_fixtures.sh [--smoke | --new | --from-fixture N --to-fixture M]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
UV="${CLOTH_STORE_UV:-/scratch4weeks/pg00807/bin/uv}"
MANIFEST="${ROOT}/bench/plan1_localization/manifest.json"

FROM_FIXTURE=""
TO_FIXTURE=""
MODE="manifest"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --smoke)
      MODE="smoke"
      shift
      ;;
    --new)
      MODE="new"
      shift
      ;;
    --from-fixture)
      FROM_FIXTURE="${2:-}"
      MODE="range"
      shift 2
      ;;
    --to-fixture)
      TO_FIXTURE="${2:-}"
      MODE="range"
      shift 2
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

case "${MODE}" in
  smoke)
    printf '%s\n' outfit_1
    ;;
  new)
    # Legacy alias for outfits 7-12; prefer --from-fixture/--to-fixture.
    for id in outfit_{7..12}; do
      printf '%s\n' "${id}"
    done
    ;;
  range)
    if [[ -z "${FROM_FIXTURE}" || -z "${TO_FIXTURE}" ]]; then
      echo "range mode requires --from-fixture and --to-fixture" >&2
      exit 1
    fi
    "${UV}" run python -c "
from cloth_store.catalog_paths import resolve_plan1_fixtures
for fid in resolve_plan1_fixtures(from_fixture=${FROM_FIXTURE}, to_fixture=${TO_FIXTURE}):
    print(fid)
"
    ;;
  manifest)
    "${UV}" run python -c "
from cloth_store.catalog_paths import resolve_plan1_fixtures
for fid in resolve_plan1_fixtures():
    print(fid)
" 2>/dev/null || python3 -c "
import json
from pathlib import Path
m = json.loads(Path('${MANIFEST}').read_text())
for f in m['fixtures']:
    print(f['id'])
"
    ;;
esac
