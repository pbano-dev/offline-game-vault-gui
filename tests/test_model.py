from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from offline_game_vault_gui.model import (
    CompositionResult,
    RunnerRecord,
    SaveSetRecord,
)


class ModelTests(unittest.TestCase):
    def test_runner_preserves_case_sensitive_identifier(self) -> None:
        runner = RunnerRecord.from_dict(
            {
                "runner_id": "GE-Proton11-1",
                "digest": "a" * 64,
                "archive_path": "objects/runner.tar.zst",
                "size": 123,
                "format": "tar.zst",
                "source_root": ".",
                "wine_path": "files/bin/wine",
                "wineserver_path": "files/bin/wineserver",
                "compatible_backends": ["bottles", "direct-wine", "umu"],
                "metadata_source": "capsule",
                "proton_path": "proton",
                "kind": "proton",
            }
        )
        self.assertEqual(runner.runner_id, "GE-Proton11-1")
        self.assertTrue(runner.supports("umu"))

    def test_composition_result_schema(self) -> None:
        result = CompositionResult.from_dict(
            {
                "schema": 0,
                "capsule_id": "example",
                "backend": "umu",
                "runner_id": "runner",
                "profile_id": "profile",
                "destination": "/derived/example",
                "materialized": True,
                "played": False,
                "play_complete": None,
                "backend_result": {},
            }
        )
        self.assertEqual(result.destination, Path("/derived/example"))

    def test_save_set_rejects_absolute_backup_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            record = SaveSetRecord(
                capsule_id="example",
                save_set_id="save",
                display_name="Save",
                captured_at="",
                captured_at_basis="",
                aggregate_digest="",
                size=0,
                manifest_path=root / "index.json",
                manifest_digest="",
                items=(),
                status="candidate",
                source={"state_backup": "/outside/backup"},
            )
            self.assertIsNone(record.backup_path(root))


    def test_save_set_rejects_intermediate_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real = root / "real"
            backup = real / "backup"
            backup.mkdir(parents=True)
            (root / "linked").symlink_to(real, target_is_directory=True)
            record = SaveSetRecord(
                capsule_id="example",
                save_set_id="save",
                display_name="Save",
                captured_at="",
                captured_at_basis="",
                aggregate_digest="",
                size=0,
                manifest_path=root / "index.json",
                manifest_digest="",
                items=(),
                status="candidate",
                source={"state_backup": "linked/backup"},
            )
            self.assertIsNone(record.backup_path(root))


if __name__ == "__main__":
    unittest.main()
