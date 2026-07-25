from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from offline_game_vault_gui.catalog import CatalogError, scan_catalog
from offline_game_vault_gui.runners import scan_runners

from helpers import (
    BOTTLES_PROFILE_ID,
    GE_RUNNER_ID,
    PROFILE_ID,
    SODA_RUNNER_ID,
    create_collection,
)


class CatalogTests(unittest.TestCase):
    def test_catalog_exposes_backend_and_default_runner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, _ = create_collection(Path(temporary) / "vault")
            games, warnings = scan_catalog(root)

            self.assertEqual(warnings, ())
            self.assertEqual(len(games), 1)
            profiles = {item.profile_id: item for item in games[0].profiles}

            direct = profiles[PROFILE_ID]
            self.assertEqual(direct.mode, "playable")
            self.assertEqual(direct.backend_id, "direct-wine")
            self.assertEqual(direct.default_runner_id, GE_RUNNER_ID)

            bottles = profiles[BOTTLES_PROFILE_ID]
            self.assertEqual(bottles.mode, "base")
            self.assertEqual(bottles.backend_id, "bottles")
            self.assertEqual(bottles.default_runner_id, GE_RUNNER_ID)

            self.assertEqual(profiles["linux-base-only"].mode, "base")
            self.assertEqual(profiles["windows-base"].backend_id, "windows")

    def test_runner_catalog_discovers_ge_and_soda(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, _ = create_collection(Path(temporary) / "vault")
            runners, warnings = scan_runners(root)

            self.assertEqual(warnings, ())
            by_id = {item.runner_id: item for item in runners}
            self.assertEqual(set(by_id), {GE_RUNNER_ID, SODA_RUNNER_ID})
            self.assertEqual(by_id[GE_RUNNER_ID].wine_path, "files/bin/wine")
            self.assertEqual(by_id[GE_RUNNER_ID].format, "tar.gz")
            self.assertEqual(by_id[SODA_RUNNER_ID].format, "tar.gz")
            self.assertEqual(by_id[SODA_RUNNER_ID].wine_path, "bin/wine")
            self.assertEqual(
                by_id[SODA_RUNNER_ID].wineserver_path,
                "bin/wineserver",
            )
            self.assertTrue(by_id[SODA_RUNNER_ID].supports("direct-wine"))
            self.assertTrue(by_id[SODA_RUNNER_ID].supports("bottles"))

    def test_rejects_symlink_collection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, _ = create_collection(base / "vault")
            link = base / "link"
            link.symlink_to(root, target_is_directory=True)
            with self.assertRaises(CatalogError):
                scan_catalog(link)


if __name__ == "__main__":
    unittest.main()
