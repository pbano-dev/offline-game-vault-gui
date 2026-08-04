from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from offline_game_vault_gui.catalog import CapsuleCatalog, CatalogError


class CapsuleCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.collection = self.root / "vault"
        self.capsules = self.collection / "02_CAPSULES"
        self.capsules.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_capsule(self, profile: dict[str, object]) -> Path:
        directory = self.capsules / "game"
        directory.mkdir()
        path = directory / "capsule.json"
        path.write_text(
            json.dumps(
                {
                    "schema": 0,
                    "capsule_id": "game",
                    "game": {"title": "Game"},
                    "profiles": [profile],
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_discovers_source_layout_without_maturity_state(self) -> None:
        path = self._write_capsule(
            {
                "id": "linux-source",
                "platform": "linux",
                "adapter": "wine",
                "playable": {"backend": "wine"},
            }
        )
        records = CapsuleCatalog().scan(self.collection)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].capsule_path, path.resolve())
        self.assertEqual(records[0].source_profiles[0].profile_id, "linux-source")
        self.assertEqual(
            records[0].source_profiles[0].playable_backend,
            "wine",
        )
        self.assertFalse(
            hasattr(records[0].source_profiles[0], "status")
        )

    def test_rejects_retired_profile_fields(self) -> None:
        self._write_capsule(
            {
                "id": "legacy",
                "platform": "linux",
                "adapter": "wine",
                "status": "candidate",
            }
        )
        with self.assertRaisesRegex(CatalogError, "retired fields"):
            CapsuleCatalog().scan(self.collection)

    def test_rejects_capsule_symlink(self) -> None:
        target = self.root / "outside.json"
        target.write_text("{}", encoding="utf-8")
        directory = self.capsules / "linked"
        directory.mkdir()
        (directory / "capsule.json").symlink_to(target)
        with self.assertRaises(CatalogError):
            CapsuleCatalog().scan(self.collection)


if __name__ == "__main__":
    unittest.main()
