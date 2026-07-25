from __future__ import annotations

import ast
from pathlib import Path
import unittest


class AppStructureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "offline_game_vault_gui"
            / "app.py"
        )
        self.tree = ast.parse(
            self.path.read_text(encoding="utf-8"),
            filename=str(self.path),
        )

    def test_vault_application_is_a_top_level_class(self) -> None:
        classes = {
            node.name: node
            for node in self.tree.body
            if isinstance(node, ast.ClassDef)
        }
        self.assertIn("VaultApplication", classes)
        vault_application = classes["VaultApplication"]
        methods = {
            node.name
            for node in vault_application.body
            if isinstance(node, ast.FunctionDef)
        }
        self.assertIn("__init__", methods)
        self.assertIn("do_activate", methods)

    def test_app_exposes_explicit_save_selection(self) -> None:
        source = self.path.read_text(encoding="utf-8")
        self.assertIn('Adw.ComboRow(title="Save set")', source)
        self.assertIn("No save (default)", source)
        self.assertIn("save_set=save_set", source)

    def test_app_uses_central_collection_resolution(self) -> None:
        source = self.path.read_text(encoding="utf-8")
        self.assertIn(
            "from .config import resolve_collection_root",
            source,
        )
        self.assertIn(
            "self.collection_root = resolve_collection_root()",
            source,
        )
        self.assertNotIn(
            'Path.home() / "Games" / "OfflineGameVault"',
            source,
        )

    def test_main_instantiates_vault_application(self) -> None:
        main = next(
            node
            for node in self.tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "main"
        )
        calls = [
            node
            for node in ast.walk(main)
            if isinstance(node, ast.Call)
        ]
        self.assertTrue(
            any(
                isinstance(call.func, ast.Name)
                and call.func.id == "VaultApplication"
                for call in calls
            )
        )


if __name__ == "__main__":
    unittest.main()
