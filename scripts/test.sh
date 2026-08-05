#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$ROOT"

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONDONTWRITEBYTECODE=1

python3 -B tools/validate_repository.py
python3 -B -m unittest discover \
    -s tests \
    -p 'test_*.py' \
    -v

if find src tests tools \
    \( -type d -name '__pycache__' -o -type f -name '*.py[co]' \) \
    -print -quit | grep -q .
then
    echo "ERROR: generated Python artifacts remain" >&2
    exit 1
fi
