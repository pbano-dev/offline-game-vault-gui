#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

python3 -B -m unittest discover -s tests -p 'test_*.py' -v

python3 -B - <<'PY'
from __future__ import annotations

import ast
from pathlib import Path

root = Path.cwd()
files = sorted(
    path
    for base in (root / "src", root / "tests", root / "scripts")
    for path in base.rglob("*.py")
)
for path in files:
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
print(f"Python AST VERIFIED: {len(files)} file(s)")
PY

while IFS= read -r -d '' script; do
    bash -n "$script"
done < <(find scripts -type f -name '*.sh' -print0 | sort -z)

echo "Shell syntax VERIFIED"

python3 -B - <<'PY'
from pathlib import Path

root = Path.cwd()
problems = []
for path in sorted(root.rglob("*")):
    if not path.is_file() or any(
        part in {".git", ".venv", "__pycache__", "dist", "build"}
        for part in path.parts
    ):
        continue
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        continue
    for number, line in enumerate(lines, 1):
        if line.rstrip(" \t") != line:
            problems.append(f"{path.relative_to(root)}:{number}: trailing whitespace")
if problems:
    raise SystemExit("\n".join(problems))
print("Whitespace audit VERIFIED")
PY

./scripts/audit-privacy.sh
echo "Repository validation VERIFIED"
