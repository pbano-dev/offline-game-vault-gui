#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd -- "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONDONTWRITEBYTECODE=1
export LC_ALL=C.UTF-8
export LANG=C.UTF-8

python3 -m compileall -q -f src tests tools
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 tools/validate_repository.py
./scripts/audit-privacy.sh
