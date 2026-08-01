from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from offline_game_vault_gui.catalog import (
    profile_backend,
    profile_mode,
    scan_catalog,
)


class CatalogTests(unittest.TestCase):
    def test_backend_and_mode_mapping(self) -> None:
        self.assertEqual(
            profile_backend({"platform": "linux", "adapter": "umu"}),
            "umu",
        )
        self.assertEqual(
            profile_mode({"platform": "linux", "adapter": "umu"}),
            "playable",
        )
        self.assertEqual(
            profile_backend({"platform": "linux", "adapter": "wine"}),
            "direct-wine",
        )
        self.assertEqual(
            profile_backend({"platform": "windows", "adapter": "windows"}),
            "windows",
        )

    def test_scans_native_umu_capsule(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capsule_id = "steam-1-test"
            directory = root / "02_CAPSULES" / capsule_id
            directory.mkdir(parents=True)
            capsule = {
                "capsule_id": capsule_id,
                "game": {
                    "title": "Synthetic Game",
                    "preserved_version": "1.0",
                },
                "objects": [],
                "profiles": [
                    {
                        "id": "linux-umu",
                        "platform": "linux",
                        "adapter": "umu",
                        "status": "candidate",
                        "dependencies": [],
                    }
                ],
            }
            (directory / "capsule.json").write_text(
                json.dumps(capsule),
                encoding="utf-8",
            )
            games, warnings = scan_catalog(root)
            self.assertEqual(warnings, ())
            self.assertEqual(len(games), 1)
            self.assertEqual(games[0].profiles[0].backend_id, "umu")


if __name__ == "__main__":
    unittest.main()
