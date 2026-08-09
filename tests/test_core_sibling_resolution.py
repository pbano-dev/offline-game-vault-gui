"""The core checkout is looked for beside the GUI repository, not above it.

Both repositories are normally cloned side by side. Searching the parent of
the parent found nothing and fell through to whatever ``ogv`` happened to be
on PATH, so the GUI reported that no core existed while one sat next to it.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from offline_game_vault_gui.core import CoreClient, CoreError


def _fake_checkout(root: Path) -> Path:
    """Minimal layout that _from_source_root accepts."""
    package = root / "src/offline_game_vault"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('__version__ = "0.0.0"\n', encoding="utf-8")
    (package / "cli.py").write_text("def main():\n    return 0\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[project]\nname = "offline-game-vault"\nversion = "0.0.0"\n',
        encoding="utf-8",
    )
    return root


class SiblingResolutionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name) / "git"
        self.workspace.mkdir(parents=True)

    def test_repository_root_means_the_gui_repository_itself(self) -> None:
        gui = self.workspace / "offline-game-vault-gui"
        gui.mkdir()
        _fake_checkout(self.workspace / "offline-game-vault")

        # repository_root is the GUI repository; the core is its sibling.
        try:
            cliente = CoreClient.resolve(repository_root=gui)
        except CoreError as exc:
            self.fail(f"no ha encontrado el core hermano: {exc}")
        self.assertIn("offline-game-vault", cliente.description)

    def test_a_missing_sibling_still_raises(self) -> None:
        gui = self.workspace / "offline-game-vault-gui"
        gui.mkdir()
        # Independent of whatever happens to be on PATH.
        with patch("offline_game_vault_gui.core.shutil.which", return_value=None):
            with self.assertRaises(CoreError):
                CoreClient.resolve(repository_root=gui)

    def test_an_installed_core_is_still_the_last_resort(self) -> None:
        gui = self.workspace / "offline-game-vault-gui"
        gui.mkdir()
        with patch(
            "offline_game_vault_gui.core.shutil.which",
            return_value="/usr/bin/ogv",
        ):
            cliente = CoreClient.resolve(repository_root=gui)
        self.assertEqual(cliente.description, "path:/usr/bin/ogv")
