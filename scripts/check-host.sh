#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$ROOT"

python3 -B - <<'PY'
from __future__ import annotations
import importlib.util
import sys

if not ((3, 11) <= sys.version_info[:2] < (3, 15)):
    raise SystemExit(
        f"Unsupported Python: {sys.version.split()[0]}; "
        "expected >=3.11,<3.15"
    )

spec = importlib.util.find_spec("PySide6")
if spec is None:
    raise SystemExit(
        "PySide6 is not installed. Install the preserved compatible wheels."
    )

import PySide6
print(f"Python: {sys.version.split()[0]}")
print(f"PySide6: {PySide6.__version__}")
PY

if [[ -n "${OGV_SOURCE_ROOT:-}" ]]; then
    CORE="$OGV_SOURCE_ROOT"
elif [[ -d "$(dirname "$ROOT")/offline-game-vault" ]]; then
    CORE="$(dirname "$ROOT")/offline-game-vault"
else
    CORE=""
fi

if [[ -n "$CORE" ]]; then
    "$ROOT/scripts/check-core-contract.sh" "$CORE"
else
    echo "Core checkout: not discovered; select it in the GUI."
fi
