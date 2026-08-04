from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from offline_game_vault_gui.save_sets import scan_save_sets


class SaveSetTests(unittest.TestCase):
    def _root(self) -> tuple[tempfile.TemporaryDirectory[str], Path, Path]:
        temporary = tempfile.TemporaryDirectory()
        collection = Path(temporary.name)
        save_root = (
            collection
            / "03_PERSISTENT_STATE/example-game/save-sets"
        )
        save_root.mkdir(parents=True)
        backup = (
            collection
            / "03_PERSISTENT_STATE/example-game/backups/main"
        )
        backup.mkdir(parents=True)
        return temporary, collection, backup

    def test_scans_and_resolves_portable_backup(self) -> None:
        temporary, collection, backup = self._root()
        self.addCleanup(temporary.cleanup)
        index = (
            collection
            / "03_PERSISTENT_STATE/example-game/save-sets/index.json"
        )
        index.write_text(
            json.dumps(
                {
                    "schema": 1,
                    "save_sets": [
                        {
                            "save_set_id": "main",
                            "display_name": "Main progress",
                            "captured_at": "2026-08-04T18:00:00Z",
                            "source": {
                                "state_backup": (
                                    "03_PERSISTENT_STATE/"
                                    "example-game/backups/main"
                                )
                            },
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        values, warnings = scan_save_sets(collection, "example-game")
        self.assertEqual(warnings, ())
        self.assertEqual(len(values), 1)
        self.assertEqual(values[0].backup_path(collection), backup.resolve())
        self.assertIn("Main progress", values[0].label)

    def test_missing_index_is_empty(self) -> None:
        temporary, collection, _backup = self._root()
        self.addCleanup(temporary.cleanup)
        values, warnings = scan_save_sets(collection, "other-game")
        self.assertEqual(values, ())
        self.assertEqual(warnings, ())

    def test_escaping_manifest_becomes_warning(self) -> None:
        temporary, collection, _backup = self._root()
        self.addCleanup(temporary.cleanup)
        index = (
            collection
            / "03_PERSISTENT_STATE/example-game/save-sets/index.json"
        )
        index.write_text(
            json.dumps(
                {
                    "save_sets": [
                        {
                            "save_set_id": "bad",
                            "manifest": "../../outside.json",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        values, warnings = scan_save_sets(collection, "example-game")
        self.assertEqual(values, ())
        self.assertEqual(len(warnings), 1)
        self.assertIn("not portable", warnings[0])


    def test_symlinked_manifest_becomes_warning(self) -> None:
        temporary, collection, _backup = self._root()
        self.addCleanup(temporary.cleanup)
        save_root = (
            collection
            / "03_PERSISTENT_STATE/example-game/save-sets"
        )
        real = save_root / "real.json"
        real.write_text(
            json.dumps({"items": []}),
            encoding="utf-8",
        )
        (save_root / "linked.json").symlink_to("real.json")
        index = save_root / "index.json"
        index.write_text(
            json.dumps(
                {
                    "save_sets": [
                        {
                            "save_set_id": "bad",
                            "manifest": "linked.json",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        values, warnings = scan_save_sets(collection, "example-game")
        self.assertEqual(values, ())
        self.assertEqual(len(warnings), 1)
        self.assertIn("symlink", warnings[0])


if __name__ == "__main__":
    unittest.main()
