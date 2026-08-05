from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src/offline_game_vault_gui/app.py"
CORE = ROOT / "src/offline_game_vault_gui/core.py"
SERVICE = ROOT / "src/offline_game_vault_gui/service.py"


class QtPresentationContractTests(unittest.TestCase):
    def test_app_imports_pyside6_and_not_gtk(self) -> None:
        tree = ast.parse(APP.read_text(encoding="utf-8"))
        roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(
                    alias.name.split(".", 1)[0]
                    for alias in node.names
                )
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module
            ):
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
            "Verified state backup",
            "QThreadPool",
        ):
            self.assertIn(token, text)

    def test_state_selection_is_backend_neutral(self) -> None:
        text = APP.read_text(encoding="utf-8")
        for token in (
            "Auto (recommended)",
            "Let the core select a source layout compatible with the backend",
            "Select verified state backup",
            "No state backup selected",
            'self._set_row_visible("save", True)',
            'self._set_row_visible("state_backup", True)',
        ):
            self.assertIn(token, text)

        request = text[
            text.index("    def _request("):
            text.index(
                "    def _compose(",
                text.index("    def _request("),
            )
        ]
        self.assertNotIn(
            'if backend == "direct-wine":',
            request,
        )

    def test_core_and_service_do_not_limit_state_to_direct_wine(
        self,
    ) -> None:
        core = CORE.read_text(encoding="utf-8")
        service = SERVICE.read_text(encoding="utf-8")
        self.assertIn(
            "if request.state_backup is not None:",
            core,
        )
        self.assertEqual(core.count("--state-backup"), 1)
        self.assertNotIn(
            "Persistent-state restoration is exposed only for",
            service,
        )

    def test_no_gtk_compatibility_layer(self) -> None:
        source = ROOT / "src/offline_game_vault_gui"
        names = {path.name for path in source.glob("*.py")}
        self.assertNotIn("gtk_app.py", names)
        self.assertNotIn("integrated_app.py", names)
        self.assertNotIn("bottles_backend.py", names)


if __name__ == "__main__":
    unittest.main()
