from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tomllib


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "SOURCE_MANIFEST_SHA256.txt"
EXCLUDED = {
    "SOURCE_MANIFEST_SHA256.txt",
}
EXCLUDED_PARTS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "build",
    "dist",
}
RETIRED_SOURCE_TERMS = (
    "experimental_selection",
    "experimental_service",
    "profile_status",
    "shared_runtime_id",
)
RETIRED_SOURCE_PATTERNS = (
    re.compile(r'\bstatus\s*:\s*str\b'),
    re.compile(r'\bacceptance_report\s*:\s*'),
)


def source_files() -> list[Path]:
    result: list[Path] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(ROOT)
        if relative.as_posix() in EXCLUDED:
            continue
        if any(
            part in EXCLUDED_PARTS or part.endswith(".egg-info")
            for part in relative.parts
        ):
            continue
        result.append(path)
    return result


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write_manifest() -> None:
    lines = [
        f"{digest(path)}  {path.relative_to(ROOT).as_posix()}"
        for path in source_files()
    ]
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")


def verify_manifest() -> None:
    if not MANIFEST.is_file() or MANIFEST.is_symlink():
        raise SystemExit("SOURCE_MANIFEST_SHA256.txt is missing or linked")
    expected: dict[str, str] = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        checksum, separator, relative = line.partition("  ")
        if not separator or not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise SystemExit(f"Invalid manifest line: {line!r}")
        if relative in expected:
            raise SystemExit(f"Duplicate manifest path: {relative}")
        expected[relative] = checksum
    actual = {
        path.relative_to(ROOT).as_posix(): digest(path)
        for path in source_files()
    }
    if expected != actual:
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        changed = sorted(
            key for key in set(expected) & set(actual)
            if expected[key] != actual[key]
        )
        raise SystemExit(
            "Manifest mismatch: "
            f"missing={missing}, extra={extra}, changed={changed}"
        )


def validate_python() -> None:
    for folder in ("src", "tests", "tools"):
        for path in sorted((ROOT / folder).rglob("*.py")):
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def validate_version() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    init = (ROOT / "src/offline_game_vault_gui/__init__.py").read_text(
        encoding="utf-8"
    )
    match = re.search(r'^__version__ = "([^"]+)"$', init, re.MULTILINE)
    if match is None:
        raise SystemExit("Package version is absent")
    values = {
        project["project"]["version"],
        match.group(1),
        "0.4.1",
    }
    if len(values) != 1:
        raise SystemExit(f"Version contract differs: {sorted(values)}")


def validate_semantics() -> None:
    for path in sorted((ROOT / "src").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for term in RETIRED_SOURCE_TERMS:
            if term in text:
                raise SystemExit(f"Retired source term {term!r} in {path}")
        for pattern in RETIRED_SOURCE_PATTERNS:
            if pattern.search(text):
                raise SystemExit(
                    f"Retired source pattern {pattern.pattern!r} in {path}"
                )


def validate_scripts() -> None:
    for path in sorted((ROOT / "scripts").glob("*.sh")):
        mode = path.stat().st_mode
        if not mode & stat.S_IXUSR:
            raise SystemExit(f"Script is not executable: {path}")


def validate_json() -> None:
    json.loads((ROOT / "UPSTREAM_BASE.json").read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-manifest", action="store_true")
    args = parser.parse_args()
    validate_python()
    validate_version()
    validate_semantics()
    validate_scripts()
    validate_json()
    if args.write_manifest:
        write_manifest()
    verify_manifest()
    print("Repository validation: passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
