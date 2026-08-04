from __future__ import annotations

import argparse
from pathlib import Path
import re


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
}

EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "build",
    "dist",
}

PATTERNS = {
    "absolute home path": re.compile(r"(?<![$<])/home/[A-Za-z0-9._-]+/"),
    "Fedora home path": re.compile(r"(?<![$<])/var/home/[A-Za-z0-9._-]+/"),
    "removable-media path": re.compile("/run/" + "media/"),
    "runtime UID path": re.compile(r"/run/user/[0-9]+/"),
    "UUID": re.compile(
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
        r"[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-"
        r"[0-9a-fA-F]{12}\b"
    ),
}


def iter_paths(root: Path):
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        yield path, relative


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    args = parser.parse_args()
    root = Path(args.root).resolve()

    failures: list[str] = []
    for path, relative in iter_paths(root):
        if path.is_symlink():
            failures.append(f"{relative}: symlink")
            continue
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(text):
                failures.append(f"{relative}: {label}")

    if failures:
        print("Privacy audit failed:")
        for item in failures:
            print(f"- {item}")
        return 1
    print("Privacy audit: passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
