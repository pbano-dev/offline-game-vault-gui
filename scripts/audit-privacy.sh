#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
export OGV_AUDIT_ROOT="$ROOT"

python3 -B - <<'PY'
from __future__ import annotations

import os
import re
from pathlib import Path

root = Path(os.environ["OGV_AUDIT_ROOT"]).resolve()
excluded_parts = {
    ".git",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    ".pytest_cache",
}
text_suffixes = {
    "",
    ".cfg",
    ".desktop",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".toml",
    ".txt",
    ".yml",
    ".yaml",
}
patterns = (
    ("absolute home path", re.compile(r"/(?:var/)?home/[A-Za-z0-9._-]+")),
    ("runtime UID path", re.compile(r"/run/user/[0-9]+")),
    ("UUID", re.compile(
        r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
        r"[89ab][0-9a-f]{3}-[0-9a-f]{12}\b"
    )),
    ("unfilled marker", re.compile(r"\[RELLENAR\]")),
)
allow = {
    "README.md": {
        "/run/user/[0-9]+",
    },
}
problems: list[str] = []

for path in sorted(root.rglob("*")):
    if not path.is_file() or any(part in excluded_parts for part in path.parts):
        continue
    if path.suffix.lower() not in text_suffixes:
        continue
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        continue
    rel = path.relative_to(root).as_posix()
    for label, pattern in patterns:
        for match in pattern.finditer(text):
            if match.group(0) in allow.get(rel, set()):
                continue
            problems.append(f"{rel}: {label}: {match.group(0)!r}")

if problems:
    print("Privacy audit FAILED")
    for problem in problems:
        print(problem)
    raise SystemExit(1)

print("Privacy audit VERIFIED")
PY
