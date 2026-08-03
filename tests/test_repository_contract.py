from __future__ import annotations

import ast
from pathlib import Path
import re
import tomllib
import unittest

from offline_game_vault_gui import __version__


ROOT = Path(__file__).resolve().parents[1]


class RepositoryContractTests(unittest.TestCase):
    def test_version_contract(self) -> None:
        project = tomllib.loads(
            (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
        self.assertEqual(__version__, "0.4.1")
        self.assertEqual(project["project"]["version"], __version__)
        self.assertIn(
            "# Offline Game Vault GUI 0.4.1",
            (ROOT / "README.md").read_text(encoding="utf-8"),
        )

    def test_required_complete_tree_files_exist(self) -> None:
        required = (
            "README.md",
            "RELEASE_NOTES.md",
            "REPOSITORY_REPLACEMENT.md",
            "SOURCE_MANIFEST_SHA256.txt",
            "UPSTREAM_BASE.json",
            "VALIDATION_REPORT.md",
            "docs/STATE_FREE_COMPONENT_MIGRATION.md",
            "src/offline_game_vault_gui/app.py",
            "src/offline_game_vault_gui/catalog.py",
            "src/offline_game_vault_gui/core.py",
            "src/offline_game_vault_gui/model.py",
            "src/offline_game_vault_gui/service.py",
            "tools/validate_repository.py",
        )
        for relative in required:
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_retired_modules_are_absent(self) -> None:
        package = ROOT / "src/offline_game_vault_gui"
        retired = (
            "experimental_selection.py",
            "experimental_service.py",
            "neutral_profiles.py",
            "runner_override.py",
            "shared_backend.py",
            "umu_overlay.py",
            "umu_state_bridge.py",
        )
        for name in retired:
            self.assertFalse((package / name).exists(), name)

    def test_python_files_parse_without_gtk_import(self) -> None:
        for folder in ("src", "tests", "tools"):
            for path in sorted((ROOT / folder).rglob("*.py")):
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_source_has_no_retired_state_contract(self) -> None:
        text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((ROOT / "src").rglob("*.py"))
        )
        for forbidden in (
            "profile_status",
            "shared_runtime_id",
            "experimental_selection",
            "experimental_service",
        ):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
