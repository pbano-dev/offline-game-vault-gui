#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
output_dir="${1:-$project_root/dist}"
mkdir -p -- "$output_dir"
output_dir="$(cd -- "$output_dir" && pwd -P)"

"$project_root/scripts/test.sh"

version="$(
    python3 -S -B - "$project_root/pyproject.toml" <<'PY'
from pathlib import Path
import sys
import tomllib

document = tomllib.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(document["project"]["version"])
PY
)"
package_name="offline-game-vault-gui-${version}"
archive="$output_dir/${package_name}-source.tar.gz"
source_date_epoch="${SOURCE_DATE_EPOCH:-0}"

temporary_root="$(mktemp -d)"
cleanup() {
    rm -rf -- "$temporary_root"
}
trap cleanup EXIT

stage="$temporary_root/$package_name"
mkdir -p -- "$stage"

tar \
    --exclude='./.git' \
    --exclude='./.venv' \
    --exclude='./venv' \
    --exclude='./__pycache__' \
    --exclude='*/__pycache__' \
    --exclude='./.pytest_cache' \
    --exclude='./.mypy_cache' \
    --exclude='./.ruff_cache' \
    --exclude='./build' \
    --exclude='./dist' \
    --exclude='*.pyc' \
    --exclude='*.pyo' \
    --exclude='*.log' \
    --exclude='*.tar.gz' \
    -C "$project_root" \
    -cf - . |
    tar -C "$stage" -xf -

find "$stage" -type d -name '__pycache__' -prune -exec rm -rf -- {} +
find "$stage" -type f \( -name '*.pyc' -o -name '*.pyo' -o -name '*.log' \) -delete

"$stage/scripts/audit-privacy.sh" "$stage"

tar \
    --sort=name \
    --format=pax \
    --pax-option=delete=atime,delete=ctime \
    --mtime="@$source_date_epoch" \
    --owner=0 \
    --group=0 \
    --numeric-owner \
    -C "$temporary_root" \
    -cf - "$package_name" |
    gzip -n >"$archive"

printf 'Created: %s\n' "$archive"
sha256sum -- "$archive"
