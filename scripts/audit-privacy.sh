#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$ROOT"
PYTHONDONTWRITEBYTECODE=1 python3 -B tools/audit_privacy.py "$ROOT"
