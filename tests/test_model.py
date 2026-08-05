from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from offline_game_vault_gui.model import (
    CompositionResult,
    RunnerRecord,
    SaveSetRecord,
    StateBackupRecord,
)


class ModelTests(unittest.TestCase):
    def test_runner_from_dict(self) -> None:
        runner = RunnerRecord.from_dict(
            {
                "runner_id": "GE-Proton11-1",
                "digest": "sha256:" + "a" * 64,
                "archive_path": "01_RUNNERS/runner.tar.zst",
                "size": 42,
                "format": "tar.zst",
                "source_root": "runner",
                "wine_path": "files/bin/wine",
                "wineserver_path": "files/bin/wineserver",
                "compatible_backends": [
                    "bottles",
                    "direct-wine",
                    "umu",
                ],
                "metadata_source": "runner.json",
                "proton_path": "proton",
                "kind": "proton",
            }
        )
        self.assertTrue(runner.supports("umu"))
        self.assertIn("GE-Proton11-1", runner.label)

    def test_runner_rejects_invalid_digest(self) -> None:
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            RunnerRecord.from_dict(
                {
                    "runner_id": "runner",
                    "digest": "bad",
                    "archive_path": "runner.tar.zst",
                    "size": 1,
                    "format": "tar.zst",
                    "source_root": "runner",
                    "wine_path": "wine",
                    "wineserver_path": "wineserver",
                    "compatible_backends": ["direct-wine"],
                    "metadata_source": "runner.json",
                    "proton_path": None,
                    "kind": "wine",
                }
            )

    def test_backend_neutral_backup_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            backup = root / "03_PERSISTENT_STATE/game/backups/main"
            backup.mkdir(parents=True)
            save = SaveSetRecord(
                capsule_id="game",
                save_set_id="main",
                display_name="Main",
                captured_at="",
                captured_at_basis="",
                aggregate_digest="",
                size=0,
                manifest_path=root / "index.json",
                manifest_digest="",
                items=(),
                status="preserved",
                source={
                    "state_backup":
                    "03_PERSISTENT_STATE/game/backups/main"
                },
            )
            self.assertEqual(save.backup_path(root), backup.resolve())

    def test_backup_path_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real = root / "real"
            real.mkdir()
            linked = root / "linked"
            linked.symlink_to(real, target_is_directory=True)
            save = SaveSetRecord(
                capsule_id="game",
                save_set_id="main",
                display_name="Main",
                captured_at="",
                captured_at_basis="",
                aggregate_digest="",
                size=0,
                manifest_path=root / "index.json",
                manifest_digest="",
                items=(),
                status="preserved",
                source={"state_backup": "linked"},
            )
            self.assertIsNone(save.backup_path(root))

    def test_composition_result_contract(self) -> None:
        result = CompositionResult.from_dict(
            {
                "schema": 0,
                "capsule_id": "game",
                "backend": "umu",
                "runner_id": "runner",
                "profile_id": "derived",
                "destination": "/tmp/derived",
                "materialized": True,
                "played": False,
                "play_complete": None,
                "backend_result": {"complete": True},
            }
        )
        self.assertEqual(result.backend, "umu")
        self.assertTrue(result.materialized)


    def test_state_backup_date_and_content_labels(self) -> None:
        backup = StateBackupRecord(
            backup_id="state-backup-example",
            path=Path("/tmp/example"),
            backup_kind="preserved",
            item_count=3,
            present_count=2,
            missing_count=1,
            total_bytes=42,
            created_at="2026-07-18T15:26:16+00:00",
            present_save_count=1,
            present_identity_count=1,
        )
        self.assertEqual(backup.recency_key[0], 1)
        self.assertNotEqual(backup.display_date, "Date unavailable")
        self.assertEqual(
            backup.content_label,
            "1 preserved save",
        )

    def test_identity_only_state_is_not_labeled_as_save(self) -> None:
        backup = StateBackupRecord(
            backup_id="state-backup-identity",
            path=Path("/tmp/identity"),
            backup_kind="preserved",
            item_count=3,
            present_count=1,
            missing_count=2,
            total_bytes=12,
            present_identity_count=1,
        )
        self.assertEqual(
            backup.content_label,
            "Identity only — no saved game",
        )
        self.assertEqual(backup.recency_key, (0, 0.0))

if __name__ == "__main__":
    unittest.main()
