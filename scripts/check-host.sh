#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONDONTWRITEBYTECODE=1

python3 -B - <<'PY'
from __future__ import annotations

import sys

if sys.version_info < (3, 11) or sys.version_info >= (3, 15):
    raise SystemExit(
        "Python 3.11 through 3.14 is required; "
        f"found {sys.version.split()[0]}"
    )

try:
    import PySide6
    from PySide6 import QtCore, QtWidgets
except ImportError as exc:
    raise SystemExit(
        "PySide6 is not installed in the selected Python environment"
    ) from exc

print(f"Python: {sys.version.split()[0]}")
print(f"PySide6: {PySide6.__version__}")
print(f"Qt: {QtCore.qVersion()}")
print(f"QtWidgets: {QtWidgets.__name__}")
PY

echo "Host dependency check: passed"
