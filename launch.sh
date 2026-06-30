#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -x "$ROOT_DIR/env/bin/python" ]]; then
  PYTHON="$ROOT_DIR/env/bin/python"
else
  PYTHON="$(command -v python3)"
fi

cd "$ROOT_DIR"
exec "$PYTHON" -m fs42.launcher "$@"
