#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
CACHE="$(mktemp -d)"
trap 'rm -rf -- "$CACHE"' EXIT

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPYCACHEPREFIX="$CACHE"

cd "$ROOT"

python3 -B - <<'PY'
from pathlib import Path

paths = sorted(
    path
    for directory in ("src", "tests", "tools")
    for path in Path(directory).rglob("*.py")
)
for path in paths:
    compile(path.read_bytes(), str(path), "exec")
print(f"Python syntax: passed ({len(paths)} files)")
PY

python3 -B -m unittest discover -s tests -v
python3 -B tools/validate_repository.py
python3 -B tools/audit_privacy.py .

echo "Test suite: passed"
