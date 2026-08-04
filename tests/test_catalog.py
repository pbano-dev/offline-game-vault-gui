from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from offline_game_vault_gui.catalog import CapsuleCatalog, CatalogError


class CapsuleCatalogTests(unittest.TestCase):
    def _collection(
        self,
        *,
        title: str = "A Very Long Example Game Title",
        extra_profile: dict[str, object] | None = None,
    ) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        capsule = root / "02_CAPSULES/example-game/capsule.json"
        capsule.parent.mkdir(parents=True)
        profile: dict[str, object] = {
            "id": "linux-source",
            "platform": "windows",
            "adapter": "direct-wine",
            "playable": {"backend": "direct-wine"},
        }
        if extra_profile:
            profile.update(extra_profile)
        capsule.write_text(
            json.dumps(
                {
                    "capsule_id": "example-game",
                    "game": {"title": title},
                    "profiles": [profile],
                }
            ),
            encoding="utf-8",
        )
        return temporary, root

    def test_discovers_game_title_and_source_layout(self) -> None:
        temporary, root = self._collection()
        self.addCleanup(temporary.cleanup)
        games = CapsuleCatalog().scan(root)
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0].title, "A Very Long Example Game Title")
        self.assertEqual(games[0].capsule_id, "example-game")
        self.assertEqual(games[0].source_profiles[0].profile_id, "linux-source")

    def test_rejects_retired_profile_fields(self) -> None:
        temporary, root = self._collection(
            extra_profile={"maturity": "verified"}
        )
        self.addCleanup(temporary.cleanup)
        with self.assertRaisesRegex(CatalogError, "retired fields"):
            CapsuleCatalog().scan(root)

    def test_rejects_capsule_directory_mismatch(self) -> None:
        temporary, root = self._collection()
        self.addCleanup(temporary.cleanup)
        path = root / "02_CAPSULES/example-game/capsule.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["capsule_id"] = "other"
        path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(CatalogError, "does not match"):
            CapsuleCatalog().scan(root)

    def test_rejects_capsule_symlink(self) -> None:
        temporary, root = self._collection()
        self.addCleanup(temporary.cleanup)
        capsule = root / "02_CAPSULES/example-game/capsule.json"
        target = capsule.with_name("real.json")
        capsule.rename(target)
        capsule.symlink_to(target.name)
        with self.assertRaises(CatalogError):
            CapsuleCatalog().scan(root)


if __name__ == "__main__":
    unittest.main()
