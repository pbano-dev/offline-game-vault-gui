#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
OUT_DIR="${1:-$ROOT/dist}"
VERSION="$(
    python3 - "$ROOT/pyproject.toml" <<'PY'
from pathlib import Path
import re
import sys

text = Path(sys.argv[1]).read_text(encoding="utf-8")
match = re.search(r'(?m)^version = "([^"]+)"$', text)
if not match:
    raise SystemExit("version not found")
print(match.group(1))
PY
)"
NAME="offline-game-vault-gui-$VERSION"
OUT="$OUT_DIR/$NAME.tar.gz"

mkdir -p -- "$OUT_DIR"

python3 - "$ROOT" "$OUT" "$NAME" <<'PY'
from __future__ import annotations

import gzip
import io
import os
import tarfile
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
output = Path(sys.argv[2]).resolve()
prefix = sys.argv[3]

excluded = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    "build",
    "dist",
}
files = [
    path
    for path in root.rglob("*")
    if path.is_file()
    and not path.is_symlink()
    and not any(part in excluded for part in path.relative_to(root).parts)
    and path != output
]
files.sort(key=lambda path: path.relative_to(root).as_posix())

directories = {prefix}
for path in files:
    current = Path(prefix)
    for part in path.relative_to(root).parts[:-1]:
        current = current / part
        directories.add(current.as_posix())

with output.open("wb") as raw:
    with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
        with tarfile.open(
            fileobj=gz,
            mode="w",
            format=tarfile.PAX_FORMAT,
        ) as archive:
            for directory in sorted(directories):
                info = tarfile.TarInfo(directory)
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mtime = 0
                archive.addfile(info)

            for path in files:
                relative = path.relative_to(root).as_posix()
                data = path.read_bytes()
                info = tarfile.TarInfo(f"{prefix}/{relative}")
                info.type = tarfile.REGTYPE
                info.size = len(data)
                info.mode = 0o755 if os.access(path, os.X_OK) else 0o644
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mtime = 0
                archive.addfile(info, io.BytesIO(data))
PY

sha256sum -- "$OUT"
