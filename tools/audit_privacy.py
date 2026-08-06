#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import sys


TEXT_SUFFIXES = {
    "",
    ".desktop",
    ".in",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    "build",
    "dist",
}
GENERIC_HOST_VALUES = {
    "localhost",
    "root",
    "runner",
    "user",
}
GENERIC_BAD_PATTERNS = (
    re.compile(r"/run/user/[0-9]+"),
    re.compile(r"/(?:home|var/home)/[^/$<\s]+"),
    re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
               r"[89ab][0-9a-f]{3}-[0-9a-f]{12}\b", re.IGNORECASE),
)


def public_files(root: Path):
    for path in sorted(root.rglob("*")):
        if any(part in EXCLUDED_PARTS for part in path.parts):
            continue
        if path.is_symlink():
            yield path
        elif path.is_file() and path.suffix in TEXT_SUFFIXES:
            yield path


def scan(root: Path) -> list[str]:
    problems: list[str] = []
    home = str(Path.home())
    username = os.environ.get("USER", "")
    hostname = os.uname().nodename

    for path in public_files(root):
        relative = path.relative_to(root)
        if path.is_symlink():
            problems.append(f"symlink: {relative} -> {os.readlink(path)}")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            continue

        concrete = [
            value
            for value in (home, username, hostname)
            if value and value not in GENERIC_HOST_VALUES
        ]
        for value in concrete:
            if value in text:
                problems.append(
                    f"private host value in {relative}: {value!r}"
                )
        for pattern in GENERIC_BAD_PATTERNS:
            if pattern.search(text):
                problems.append(
                    f"private-path pattern in {relative}: {pattern.pattern}"
                )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "root",
        nargs="?",
        type=Path,
        default=Path.cwd(),
    )
    args = parser.parse_args()
    root = args.root.resolve()
    problems = scan(root)
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        print(
            f"PRIVACY AUDIT FAILED: {len(problems)} problem(s)",
            file=sys.stderr,
        )
        return 1
    print("PRIVACY AUDIT PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
