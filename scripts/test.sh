#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
export PYTHONDONTWRITEBYTECODE=1

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
export PYTHONPATH="${project_root}/src"

bridge="${project_root}/scripts/ogv-state-capsule-bridge.py"
[[ -x "$bridge" ]] || {
    printf 'Bridge is not executable: %s\n' "$bridge" >&2
    exit 1
}
[[ "$(head -c 22 -- "$bridge")" == '#!/usr/bin/env python3' ]] || {
    printf 'The bridge shebang is not at the first byte\n' >&2
    exit 1
}
python3 -S -B "$bridge" --help >/dev/null

python3 -S -B -m unittest discover -s "${project_root}/tests" -v

while IFS= read -r -d '' script; do
    bash -n -- "$script"
done < <(
    find "${project_root}/scripts" -type f -name '*.sh' -print0
)
printf 'Shell syntax: OK\n'

python3 -S -B -c '
from pathlib import Path
import ast
import sys

root = Path(sys.argv[1])
for path in sorted(root.rglob("*.py")):
    if any(part in {".git", ".venv", "venv", "__pycache__", "build", "dist"} for part in path.parts):
        continue
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
print("Python AST: OK")
' "$project_root"

"$project_root/scripts/audit-privacy.sh" "$project_root"
