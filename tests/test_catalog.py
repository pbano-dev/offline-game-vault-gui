from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from offline_game_vault_gui.catalog import CapsuleCatalog, CatalogError


class CatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.capsules = self.root / "02_CAPSULES"
        self.capsules.mkdir()

    def write_capsule(
        self,
        capsule_id: str,
        title: str,
        profile: dict[str, object] | None = None,
    ) -> Path:
        directory = self.capsules / capsule_id
        directory.mkdir()
        path = directory / "capsule.json"
        path.write_text(
            json.dumps(
                {
                    "capsule_id": capsule_id,
                    "game": {"title": title},
                    "profiles": [
                        profile
                        or {
                            "id": "source",
                            "platform": "windows",
                            "adapter": "direct-wine",
                            "playable": {
                                "backend": "direct-wine"
                            },
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_scans_and_sorts_games(self) -> None:
        self.write_capsule("z-game", "Zulu")
        self.write_capsule("a-game", "Alpha")
        games = CapsuleCatalog().scan(self.root)
        self.assertEqual(
            [item.capsule_id for item in games],
            ["a-game", "z-game"],
        )
        self.assertEqual(
            games[0].source_profiles[0].playable_backend,
            "direct-wine",
        )

    def test_rejects_retired_profile_state(self) -> None:
        self.write_capsule(
            "game",
            "Game",
            {
                "id": "source",
                "platform": "windows",
                "adapter": "direct-wine",
                "status": "accepted",
            },
        )
        with self.assertRaisesRegex(
            CatalogError,
            "retired state fields",
        ):
            CapsuleCatalog().scan(self.root)

    def test_requires_capsules_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(
                CatalogError,
                "02_CAPSULES",
            ):
                CapsuleCatalog().scan(Path(temporary))


if __name__ == "__main__":
    unittest.main()
