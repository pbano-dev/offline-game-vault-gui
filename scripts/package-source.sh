#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
PARENT="$(dirname -- "$ROOT")"
NAME="$(basename -- "$ROOT")"
OUTPUT="${1:-$PARENT/${NAME}.zip}"

cd "$ROOT"
python3 -B tools/validate_repository.py --write-manifest
./scripts/test.sh

rm -f -- "$OUTPUT"
(
    cd "$PARENT"
    python3 -B - "$NAME" "$OUTPUT" <<'PY'
from __future__ import annotations

from pathlib import Path
import sys
import zipfile

name = Path(sys.argv[1])
output = Path(sys.argv[2])

excluded_parts = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "build",
    "dist",
}

with zipfile.ZipFile(
    output,
    "w",
    compression=zipfile.ZIP_DEFLATED,
    compresslevel=9,
) as archive:
    for path in sorted(name.rglob("*")):
        relative = path.relative_to(name)
        if any(part in excluded_parts for part in relative.parts):
            continue
        if path.is_symlink():
            raise SystemExit(f"Refusing symlink: {relative}")
        if path.is_file() and path.suffix not in {".pyc", ".pyo"}:
            info = zipfile.ZipInfo.from_file(
                path,
                arcname=str(name / relative),
            )
            info.date_time = (2026, 8, 4, 0, 0, 0)
            data = path.read_bytes()
            archive.writestr(
                info,
                data,
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )
PY
)

sha256sum -- "$OUTPUT"
echo "Source ZIP created: $OUTPUT"
