#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import stat
import subprocess
import sys
import tomllib


MANIFEST = "SOURCE_MANIFEST_SHA256.txt"
EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    "build",
    "dist",
}
EXCLUDED_FILES = {
    MANIFEST,
}


def included_files(root: Path) -> tuple[Path, ...]:
    result: list[Path] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        if path.is_symlink():
            raise RuntimeError(
                f"source tree contains a symlink: {relative}"
            )
        if path.is_file() and relative.as_posix() not in EXCLUDED_FILES:
            result.append(path)
    return tuple(sorted(result))


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def manifest_text(root: Path) -> str:
    return "".join(
        f"{digest(path)}  {path.relative_to(root).as_posix()}\n"
        for path in included_files(root)
    )


def validate_syntax(root: Path) -> None:
    for directory in ("src", "tests", "tools"):
        for path in sorted((root / directory).rglob("*.py")):
            compile(path.read_bytes(), str(path), "exec")

    for path in sorted(root.rglob("*.json")):
        if any(part in EXCLUDED_PARTS for part in path.parts):
            continue
        json.loads(path.read_text(encoding="utf-8"))

    tomllib.loads(
        (root / "pyproject.toml").read_text(encoding="utf-8")
    )

    for path in sorted((root / "scripts").glob("*.sh")):
        mode = path.stat().st_mode
        if not mode & stat.S_IXUSR:
            raise RuntimeError(
                f"script is not executable: {path.relative_to(root)}"
            )
        process = subprocess.run(
            ["bash", "-n", str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if process.returncode != 0:
            raise RuntimeError(
                f"invalid shell syntax in {path.relative_to(root)}: "
                f"{process.stderr.strip()}"
            )


def validate_version(root: Path) -> str:
    project = tomllib.loads(
        (root / "pyproject.toml").read_text(encoding="utf-8")
    )
    namespace: dict[str, object] = {}
    path = root / "src/offline_game_vault_gui/__init__.py"
    exec(compile(path.read_bytes(), str(path), "exec"), namespace)
    project_version = project["project"]["version"]
    package_version = namespace.get("__version__")
    if project_version != package_version:
        raise RuntimeError(
            f"version mismatch: {project_version!r} != {package_version!r}"
        )
    return str(project_version)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--write-manifest",
        action="store_true",
    )
    parser.add_argument(
        "--skip-manifest",
        action="store_true",
    )
    parser.add_argument(
        "root",
        nargs="?",
        type=Path,
        default=Path.cwd(),
    )
    args = parser.parse_args()
    root = args.root.resolve()

    try:
        validate_syntax(root)
        version = validate_version(root)
        expected = manifest_text(root)
        manifest = root / MANIFEST
        if args.write_manifest:
            manifest.write_text(expected, encoding="utf-8")
        elif not args.skip_manifest:
            if manifest.is_symlink() or not manifest.is_file():
                raise RuntimeError("source manifest is absent or unsafe")
            actual = manifest.read_text(encoding="utf-8")
            if actual != expected:
                raise RuntimeError(
                    "source manifest does not match the repository tree"
                )
    except (
        OSError,
        RuntimeError,
        SyntaxError,
        json.JSONDecodeError,
        tomllib.TOMLDecodeError,
    ) as exc:
        print(f"VALIDATION FAILED: {exc}", file=sys.stderr)
        return 1

    print(
        f"VALIDATION PASSED: version={version}, "
        f"files={len(included_files(root))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
