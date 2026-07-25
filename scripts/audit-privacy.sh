#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

project_root="${1:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)}"
project_root="$(cd -- "$project_root" && pwd -P)"
export OGV_PRIVACY_AUDIT_ROOT="$project_root"

python3 -S -B <<'PY'
from __future__ import annotations

import os
from pathlib import Path
import re
import sys

root = Path(os.environ["OGV_PRIVACY_AUDIT_ROOT"]).resolve()
excluded_dirs = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "build",
    "dist",
    "htmlcov",
}
excluded_files = {
    Path("scripts/audit-privacy.sh"),
}
synthetic_home_users = {"example-user"}
text_suffixes = {
    "",
    ".cfg",
    ".desktop",
    ".in",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
raw_log_suffixes = {".log", ".trace"}
compiled_suffixes = {".pyc", ".pyo"}
uuid_re = re.compile(
    rb"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
    rb"[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-"
    rb"[0-9a-fA-F]{12}\b"
)
home_re = re.compile(rb"/(?:var/)?home/([A-Za-z0-9._-]+)")
run_user_re = re.compile(rb"/run/user/[0-9]+(?:/|\\b)")
private_key_re = re.compile(rb"-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----")
forbidden_build_path_re = re.compile(rb"/mnt/" rb"data/")

markers = [
    marker.encode("utf-8")
    for marker in os.environ.get("OGV_PRIVATE_MARKERS", "").splitlines()
    if marker
]

findings: list[str] = []

for path in sorted(root.rglob("*")):
    relative = path.relative_to(root)
    if any(part in excluded_dirs for part in relative.parts):
        continue

    if path.is_symlink():
        target = os.readlink(path)
        findings.append(f"symbolic link requires review: {relative} -> {target}")
        continue

    if not path.is_file():
        continue

    if path.suffix.lower() in raw_log_suffixes:
        findings.append(f"raw log file: {relative}")
    if path.suffix.lower() in compiled_suffixes:
        findings.append(f"compiled Python file: {relative}")
    if relative in excluded_files:
        continue

    try:
        data = path.read_bytes()
    except OSError as exc:
        findings.append(f"unreadable file: {relative}: {exc}")
        continue

    if b"\0" in data:
        findings.append(f"binary file requires a separate privacy audit: {relative}")
        continue

    if path.suffix.lower() not in text_suffixes:
        findings.append(f"unclassified text file requires review: {relative}")

    if forbidden_build_path_re.search(data):
        findings.append(f"build-environment path in {relative}")
    if run_user_re.search(data):
        findings.append(f"runtime UID path in {relative}")
    if uuid_re.search(data):
        findings.append(f"UUID-like identifier in {relative}")
    if private_key_re.search(data):
        findings.append(f"private-key material in {relative}")

    for match in home_re.finditer(data):
        user = match.group(1).decode("ascii", errors="replace")
        if user not in synthetic_home_users:
            findings.append(f"home-directory identity in {relative}: {user}")

    for marker in markers:
        if marker in data:
            findings.append(f"caller-supplied private marker in {relative}")

if findings:
    print("Privacy audit: FAILED", file=sys.stderr)
    for finding in sorted(set(findings)):
        print(f"- {finding}", file=sys.stderr)
    raise SystemExit(1)

print("Privacy audit: OK")
PY
