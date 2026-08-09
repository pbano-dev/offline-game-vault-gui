from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from offline_game_vault_gui.save_sets import scan_save_sets


class SaveSetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.save_root = (
            self.root
            / "03_PERSISTENT_STATE/game/save-sets"
        )
        self.save_root.mkdir(parents=True)
        self.backup = (
            self.root
            / "03_PERSISTENT_STATE/game/backups/main"
        )
        self.backup.mkdir(parents=True)

    def test_scans_portable_backend_neutral_backup(self) -> None:
        index = self.save_root / "index.json"
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
                                "state_backup":
                                "03_PERSISTENT_STATE/game/backups/main"
                            },
                            "items": [
                                {
                                    "state_id": "save",
                                    "path": "drive_c/save",
                                    "size": 12,
                                }
                            ],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        values, warnings = scan_save_sets(self.root, "game")
        self.assertEqual(warnings, ())
        self.assertEqual(len(values), 1)
        self.assertEqual(
            values[0].backup_path(self.root),
            self.backup.resolve(),
        )
        self.assertEqual(values[0].items[0].state_id, "save")

    def test_unsafe_manifest_is_reported_not_followed(self) -> None:
        (self.save_root / "index.json").write_text(
            json.dumps(
                {
                    "save_sets": [
                        {
                            "save_set_id": "unsafe",
                            "manifest": "../../outside.json",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        values, warnings = scan_save_sets(self.root, "game")
        self.assertEqual(values, ())
        self.assertEqual(len(warnings), 1)
        self.assertIn("not portable", warnings[0])

    def test_missing_optional_index_is_empty(self) -> None:
        (self.save_root / "index.json").unlink(missing_ok=True)
        values, warnings = scan_save_sets(self.root, "game")
        self.assertEqual(values, ())
        self.assertEqual(warnings, ())


if __name__ == "__main__":
    unittest.main()
