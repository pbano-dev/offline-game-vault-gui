from __future__ import annotations

import argparse
import ast
import hashlib
from pathlib import Path
import subprocess
import sys
import tomllib


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "SOURCE_MANIFEST_SHA256.txt"

REQUIRED = {
    ".github/workflows/validate.yml",
    ".editorconfig",
    ".gitignore",
    "LICENSE",
    "MANIFEST.in",
    "README.md",
    "RELEASE_NOTES.md",
    "REPOSITORY_REPLACEMENT.md",
    "SOURCE_MANIFEST_SHA256.txt",
    "UPSTREAM_BASE.json",
    "VALIDATION_REPORT.md",
    "pyproject.toml",
    "requirements-lock.txt",
    "requirements-ci.txt",
    "data/io.github.pbano.OfflineGameVault.Gui.desktop",
    "docs/ARCHITECTURE.md",
    "docs/THIRD_PARTY.md",
    "scripts/audit-privacy.sh",
    "scripts/check-core-contract.sh",
    "scripts/check-host.sh",
    "scripts/package-source.sh",
    "scripts/run-dev.sh",
    "scripts/test.sh",
    "src/offline_game_vault_gui/__init__.py",
    "src/offline_game_vault_gui/app.py",
    "src/offline_game_vault_gui/catalog.py",
    "src/offline_game_vault_gui/config.py",
    "src/offline_game_vault_gui/core.py",
    "src/offline_game_vault_gui/model.py",
    "src/offline_game_vault_gui/save_sets.py",
    "src/offline_game_vault_gui/service.py",
    "tests/test_catalog.py",
    "tests/test_config.py",
    "tests/test_core.py",
    "tests/test_model.py",
    "tests/test_qt_contract.py",
    "tests/test_qt_smoke.py",
    "tests/test_repository_contract.py",
    "tests/test_save_sets.py",
    "tests/test_service.py",
    "tools/audit_privacy.py",
    "tools/validate_repository.py",
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

EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".zip"}


def source_files() -> list[Path]:
    result: list[Path] = []
    for path in ROOT.rglob("*"):
        if path == MANIFEST:
            continue
        relative = path.relative_to(ROOT)
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        if path.is_symlink():
            raise SystemExit(f"Repository contains a symlink: {relative}")
        if path.is_file() and path.suffix not in EXCLUDED_SUFFIXES:
            result.append(path)
    return sorted(result, key=lambda item: item.relative_to(ROOT).as_posix())


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def manifest_text() -> str:
    return "".join(
        f"{digest(path)}  {path.relative_to(ROOT).as_posix()}\n"
        for path in source_files()
    )


def validate_required() -> None:
    missing = sorted(
        relative
        for relative in REQUIRED
        if not (ROOT / relative).is_file()
    )
    if missing:
        raise SystemExit(
            "Missing required files:\n" + "\n".join(missing)
        )


def validate_versions() -> None:
    project = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    version = project["project"]["version"]
    namespace: dict[str, object] = {}
    exec(
        compile(
            (ROOT / "src/offline_game_vault_gui/__init__.py").read_bytes(),
            "__init__.py",
            "exec",
        ),
        namespace,
    )
    package_version = namespace.get("__version__")
    if version != package_version:
        raise SystemExit(
            f"Version mismatch: pyproject={version}, package={package_version}"
        )
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    if version not in readme:
        raise SystemExit("README does not state the package version")


def imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def validate_presentation_layer() -> None:
    source = ROOT / "src/offline_game_vault_gui"
    all_roots: set[str] = set()
    for path in source.glob("*.py"):
        all_roots.update(imported_roots(path))
    retired = sorted({"gi", "Gtk", "Adw"}.intersection(all_roots))
    if retired:
        raise SystemExit(
            "Retired GTK presentation imports remain: "
            + ", ".join(retired)
        )
    app_roots = imported_roots(source / "app.py")
    if "PySide6" not in app_roots:
        raise SystemExit("app.py does not import PySide6")
    app_text = (source / "app.py").read_text(encoding="utf-8")
    for required in (
        "QMainWindow",
        "QComboBox",
        "QFormLayout",
        "QThreadPool",
        "Preserved save set",
    ):
        if required not in app_text:
            raise SystemExit(f"Qt frontend contract is missing: {required}")


def validate_shell() -> None:
    for path in sorted((ROOT / "scripts").glob("*.sh")):
        result = subprocess.run(
            ["bash", "-n", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise SystemExit(
                f"Shell syntax failed for {path.name}: {result.stderr}"
            )


def validate_manifest(write: bool) -> None:
    expected = manifest_text()
    if write:
        MANIFEST.write_text(expected, encoding="utf-8")
        return
    if not MANIFEST.is_file():
        raise SystemExit("SOURCE_MANIFEST_SHA256.txt is missing")
    actual = MANIFEST.read_text(encoding="utf-8")
    if actual != expected:
        raise SystemExit(
            "SOURCE_MANIFEST_SHA256.txt is stale; run "
            "tools/validate_repository.py --write-manifest"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-manifest", action="store_true")
    args = parser.parse_args()

    validate_required()
    validate_versions()
    validate_presentation_layer()
    validate_shell()
    validate_manifest(args.write_manifest)
    print("Repository validation: passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
