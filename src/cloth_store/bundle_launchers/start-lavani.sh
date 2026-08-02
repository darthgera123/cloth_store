#!/usr/bin/env sh
# Lavani's Closet — local static preview (Python stdlib HTTP server).
set -eu

cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

PYTHON=""
if command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON=python
else
  echo ""
  echo "Python 3 is not installed or not on PATH."
  echo "Install Python 3 from https://www.python.org/downloads/ or your package manager."
  echo ""
  exit 1
fi

PORT=8080
URL="http://127.0.0.1:${PORT}/"

echo ""
echo "Lavani's Closet - local preview at http://127.0.0.1:8080/"
echo "Press Ctrl+C to stop the server."
echo ""

if command -v open >/dev/null 2>&1; then
  open "${URL}" >/dev/null 2>&1 &
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "${URL}" >/dev/null 2>&1 &
fi

exec "$PYTHON" -m http.server "${PORT}" --bind 127.0.0.1
