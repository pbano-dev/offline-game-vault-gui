#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
OUTPUT="${1:-$ROOT/../offline-game-vault-gui-PySide6-0.5.0a3.zip}"

cd "$ROOT"
python3 -B tools/validate_repository.py
python3 -B tools/audit_privacy.py "$ROOT"

python3 -B - "$ROOT" "$OUTPUT" <<'PY'
from __future__ import annotations
from pathlib import Path
import stat
import sys
import zipfile

root = Path(sys.argv[1]).resolve()
output = Path(sys.argv[2]).expanduser().resolve()
name = root.name
excluded_parts = {
    ".git",
    ".venv",
    "__pycache__",
    "build",
    "dist",
}
excluded_suffixes = {".pyc", ".pyo"}

files = []
for path in root.rglob("*"):
    relative = path.relative_to(root)
    if any(part in excluded_parts for part in relative.parts):
        continue
    if path.is_symlink():
        raise SystemExit(f"Refusing source symlink: {relative}")
    if path.is_file() and path.suffix not in excluded_suffixes:
        files.append(path)

output.parent.mkdir(parents=True, exist_ok=True)
temporary = output.with_name(output.name + ".tmp")
with zipfile.ZipFile(
    temporary,
    "w",
    compression=zipfile.ZIP_DEFLATED,
    compresslevel=9,
) as archive:
    for path in sorted(files):
        relative = path.relative_to(root)
        info = zipfile.ZipInfo(
            f"{name}/{relative.as_posix()}",
            date_time=(2026, 8, 4, 0, 0, 0),
        )
        mode = path.stat().st_mode & 0o777
        info.create_system = 3
        info.external_attr = (
            (stat.S_IFREG | mode) << 16
        )
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, path.read_bytes())

temporary.replace(output)
print(output)
PY

sha256sum "$OUTPUT"
