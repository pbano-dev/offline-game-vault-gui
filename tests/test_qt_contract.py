from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src/offline_game_vault_gui/app.py"


class QtPresentationContractTests(unittest.TestCase):
    def test_app_imports_pyside6_and_not_gtk(self) -> None:
        tree = ast.parse(APP.read_text(encoding="utf-8"))
        roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module.split(".", 1)[0])
        self.assertIn("PySide6", roots)
        self.assertNotIn("gi", roots)

    def test_qt_widgets_and_wrapped_game_selector_exist(self) -> None:
        text = APP.read_text(encoding="utf-8")
        for token in (
            "QMainWindow",
            "QFormLayout",
            "QComboBox",
            "RichComboBox",
            "TextWordWrap",
            "Preserved save set",
            "QThreadPool",
        ):
            self.assertIn(token, text)

    def test_no_gtk_compatibility_layer(self) -> None:
        source = ROOT / "src/offline_game_vault_gui"
        names = {path.name for path in source.glob("*.py")}
        self.assertNotIn("gtk_app.py", names)
        self.assertNotIn("integrated_app.py", names)
        self.assertNotIn("bottles_backend.py", names)


if __name__ == "__main__":
    unittest.main()
