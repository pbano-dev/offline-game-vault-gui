#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
NAME="offline-game-vault-gui-state-free-components-0.4.1"
OUT="${1:-$ROOT/dist}"
STAGE="$(mktemp -d)"
trap 'rm -rf -- "$STAGE"' EXIT

cd -- "$ROOT"
find src tests tools -type d -name __pycache__ -prune -exec rm -rf -- {} +
find src -maxdepth 1 -type d -name "*.egg-info" -prune -exec rm -rf -- {} +
./scripts/test.sh

python3 tools/validate_repository.py --write-manifest
./scripts/test.sh

find src tests tools -type d -name __pycache__ -prune -exec rm -rf -- {} +
find src -maxdepth 1 -type d -name "*.egg-info" -prune -exec rm -rf -- {} +
mkdir -p -- "$OUT" "$STAGE/$NAME"
cp -a \
    .editorconfig .github .gitignore LICENSE MANIFEST.in README.md \
    RELEASE_NOTES.md REPOSITORY_REPLACEMENT.md SOURCE_MANIFEST_SHA256.txt \
    UPSTREAM_BASE.json VALIDATION_REPORT.md data docs pyproject.toml scripts \
    src tests tools \
    "$STAGE/$NAME/"

python3 - "$STAGE" "$OUT/$NAME.zip" "$NAME" <<'PY'
from pathlib import Path
import sys
import zipfile

stage = Path(sys.argv[1])
output = Path(sys.argv[2])
name = sys.argv[3]
with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    for path in sorted((stage / name).rglob("*")):
        if path.is_file():
            archive.write(path, path.relative_to(stage).as_posix())
PY

EXTRACT="$STAGE/extracted"
mkdir -p -- "$EXTRACT"
python3 - "$OUT/$NAME.zip" "$EXTRACT" <<'PY'
from pathlib import Path
import sys
import zipfile
archive = Path(sys.argv[1])
destination = Path(sys.argv[2])
with zipfile.ZipFile(archive) as handle:
    for info in handle.infolist():
        member = Path(info.filename)
        if member.is_absolute() or ".." in member.parts:
            raise SystemExit(f"unsafe ZIP member: {info.filename}")
        raw_mode = (info.external_attr >> 16)
        kind = raw_mode & 0o170000
        if kind == 0o120000:
            raise SystemExit(f"symlink ZIP member: {info.filename}")
        target = destination / member
        target.parent.mkdir(parents=True, exist_ok=True)
        with handle.open(info) as source, target.open("wb") as output:
            output.write(source.read())
        target.chmod(raw_mode & 0o777 or 0o644)
PY

cd -- "$EXTRACT/$NAME"
sha256sum -c SOURCE_MANIFEST_SHA256.txt
./scripts/test.sh

sha256sum -- "$OUT/$NAME.zip"
