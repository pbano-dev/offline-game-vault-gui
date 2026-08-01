from __future__ import annotations

import unittest
from pathlib import Path

import offline_game_vault_gui


class ReleasePolicyTests(unittest.TestCase):
    def test_version_and_single_entry_point(self) -> None:
        root = Path(__file__).resolve().parents[1]
        pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('version = "0.3.3"', pyproject)
        self.assertIn(
            'ogv-gui = "offline_game_vault_gui.integrated_app:main"',
            pyproject,
        )
        self.assertNotIn("ogv-umu-gui", pyproject)
        self.assertEqual(offline_game_vault_gui.__version__, "0.3.3")

    def test_active_gui_exposes_all_linux_backends_for_every_game(self) -> None:
        root = Path(__file__).resolve().parents[1]
        selection = (
            root
            / "src/offline_game_vault_gui/experimental_selection.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'BACKENDS = ("bottles", "direct-wine", "umu")',
            selection,
        )
        self.assertNotIn("601150", selection)
        self.assertNotIn("native_umu_only", selection)

    def test_gui_exposes_materialize_and_play(self) -> None:
        root = Path(__file__).resolve().parents[1]
        app = (
            root
            / "src/offline_game_vault_gui/integrated_app.py"
        ).read_text(encoding="utf-8")
        self.assertIn('label="Materialize & Play"', app)
        self.assertIn("materialize_experimental(", app)
        self.assertIn("run_experimental(", app)
        self.assertNotIn("Export for Windows", app)

    def test_core_is_validated_before_catalog_use(self) -> None:
        root = Path(__file__).resolve().parents[1]
        app = (
            root
            / "src/offline_game_vault_gui/integrated_app.py"
        ).read_text(encoding="utf-8")
        self.assertIn("validate_core()", app)
        self.assertIn("list_preserved_runners(", app)
        self.assertNotIn("Preserved UMU backend", app)

    def test_bottles_path_is_detected_and_not_user_selectable(self) -> None:
        root = Path(__file__).resolve().parents[1]
        app = (
            root
            / "src/offline_game_vault_gui/integrated_app.py"
        ).read_text(encoding="utf-8")
        self.assertIn("discover_bottles_path()", app)
        self.assertIn(
            "Detected from bottles-cli; it cannot be overridden",
            app,
        )
        self.assertNotIn("Choose Bottles directory", app)
        self.assertNotIn("select_bottles_path", app)

    def test_no_separate_umu_application_is_packaged(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.assertFalse(
            (
                root
                / "src/offline_game_vault_gui/umu_app.py"
            ).exists()
        )
        self.assertFalse((root / "scripts/run-umu-dev.sh").exists())


if __name__ == "__main__":
    unittest.main()
