from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from offline_game_vault_gui.model import (
    CompositionRequest,
    CompositionResult,
    GameRecord,
    SourceProfile,
    StateBackupRecord,
)
from offline_game_vault_gui.service import (
    CompositionService,
    ServiceError,
)


class FakeCore:
    def list_runners(self, collection_root: Path):
        del collection_root
        return (), ()

    def list_component_sets(self, collection_root: Path):
        del collection_root
        return ()

    def discover_bottles_path(self) -> Path:
        raise AssertionError(
            "not used in this synthetic service test"
        )

    def verify_state_backup(
        self,
        *,
        capsule_path: Path,
        backup: Path,
    ) -> StateBackupRecord:
        del capsule_path
        return StateBackupRecord(
            backup_id="verified-backup",
            path=backup,
            backup_kind="accepted",
            item_count=1,
            present_count=1,
            missing_count=0,
            total_bytes=12,
        )

    def compose(
        self,
        request: CompositionRequest,
    ) -> CompositionResult:
        assert request.destination is not None
        if request.backend == "bottles":
            assert request.bottles_path is not None
            assert request.bottle_name is not None
        destination = request.destination

        destination.mkdir()
        for name in (
            "JUGAR.sh",
            "VERIFICAR.sh",
            "DESINSTALAR.sh",
        ):
            script = destination / name
            script.write_text(
                "#!/bin/sh\nexit 0\n",
                encoding="utf-8",
            )
            script.chmod(0o755)

        return CompositionResult(
            capsule_id="example-game",
            backend=request.backend,
            runner_id=request.runner_id,
            profile_id="derived",
            destination=destination,
            materialized=True,
            played=request.play,
            play_complete=True if request.play else None,
            backend_result={},
        )


class CompositionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.collection = self.root / "collection"
        capsule = (
            self.collection
            / "02_CAPSULES/example-game/capsule.json"
        )
        capsule.parent.mkdir(parents=True)
        capsule.write_text(
            json.dumps(
                {
                    "capsule_id": "example-game",
                    "game": {"title": "Example"},
                    "profiles": [
                        {
                            "id": "source",
                            "platform": "windows",
                            "adapter": "direct-wine",
                        }
                    ],
                    "persistent_state": [
                        {
                            "id": "save",
                            "path": "drive_c/save",
                            "backup": True,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        self.capsule = capsule
        self.destination_parent = self.root / "derived"
        self.destination_parent.mkdir()
        self.bottles = self.root / "bottles"
        self.bottles.mkdir()
        self.state_backup = self.root / "state-backup"
        self.state_backup.mkdir()
        self.service = CompositionService(
            FakeCore()  # type: ignore[arg-type]
        )
        self.counter = 0

    def request(
        self,
        *,
        backend: str = "direct-wine",
        state_backup: Path | None = None,
        save_set_id: str | None = None,
        no_state: bool = False,
    ) -> CompositionRequest:
        self.counter += 1
        common: dict[str, object] = {
            "collection_root": self.collection,
            "capsule_path": self.capsule,
            "backend": backend,
            "runner_id": "runner",
            "state_backup": state_backup,
            "save_set_id": save_set_id,
            "no_state": no_state,
        }
        common["destination"] = (
            self.destination_parent
            / f"example-{self.counter}"
        )
        if backend == "bottles":
            common.update(
                bottles_path=self.bottles,
                bottle_name=f"example-{self.counter}",
            )
        return CompositionRequest(
            **common  # type: ignore[arg-type]
        )

    def test_materializes_and_writes_minimized_receipt(self) -> None:
        state_home = self.root / "state"
        with patch.dict(
            os.environ,
            {"XDG_STATE_HOME": str(state_home)},
            clear=False,
        ):
            result = self.service.compose(
                self.request(
                    state_backup=self.state_backup,
                    save_set_id="main",
                )
            )

        self.assertTrue(result.materialized)
        receipts = list(
            (
                state_home
                / "offline-game-vault-gui/operations"
            ).glob("*.json")
        )
        self.assertEqual(len(receipts), 1)
        text = receipts[0].read_text(encoding="utf-8")
        document = json.loads(text)
        self.assertEqual(
            document["request"]["save_set_id"],
            "main",
        )
        self.assertTrue(
            document["request"][
                "state_backup_selected"
            ]
        )
        self.assertNotIn(str(self.state_backup), text)
        self.assertNotIn(str(result.destination), text)

    def test_accepts_state_backup_for_every_backend(self) -> None:
        state_home = self.root / "state-all"
        with patch.dict(
            os.environ,
            {"XDG_STATE_HOME": str(state_home)},
            clear=False,
        ):
            for backend in (
                "bottles",
                "direct-wine",
                "umu",
            ):
                with self.subTest(backend=backend):
                    result = self.service.compose(
                        self.request(
                            backend=backend,
                            state_backup=self.state_backup,
                            save_set_id="main",
                        )
                    )
                    self.assertEqual(
                        result.backend,
                        backend,
                    )
                    self.assertTrue(result.materialized)

    def test_allows_explicit_no_state_with_preservable_capsule(
        self,
    ) -> None:
        state_home = self.root / "state-clean"
        core = self.service.core
        with (
            patch.dict(
                os.environ,
                {"XDG_STATE_HOME": str(state_home)},
                clear=False,
            ),
            patch.object(
                core,
                "compose",
                wraps=core.compose,
            ) as compose,
        ):
            result = self.service.compose(
                self.request(no_state=True)
            )
        self.assertTrue(result.materialized)
        normalized = compose.call_args.args[0]
        self.assertTrue(normalized.no_state)
        self.assertIsNone(normalized.state_backup)

    def test_rejects_no_state_with_state_backup(self) -> None:
        with self.assertRaisesRegex(
            ServiceError,
            "cannot also restore",
        ):
            self.service.compose(
                self.request(
                    state_backup=self.state_backup,
                    no_state=True,
                )
            )

    def test_discovers_verified_backups_and_uses_auto_source(self) -> None:
        backup = (
            self.collection
            / "03_PERSISTENT_STATE/example-game/backups/main"
        )
        backup.mkdir(parents=True)
        (backup / "state-backup.json").write_text(
            "{}\n",
            encoding="utf-8",
        )
        save_root = (
            self.collection
            / "03_PERSISTENT_STATE/example-game/save-sets"
        )
        save_root.mkdir(parents=True)
        (save_root / "index.json").write_text(
            json.dumps(
                {
                    "save_sets": [
                        {
                            "save_set_id": "main",
                            "display_name": "Main progress",
                            "source": {
                                "state_backup": (
                                    "03_PERSISTENT_STATE/"
                                    "example-game/backups/main"
                                )
                            },
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        game = GameRecord(
            capsule_id="example-game",
            title="Example",
            capsule_path=self.capsule,
            source_profiles=(
                SourceProfile(
                    profile_id="linux-bottles-flatpak",
                    platform="linux",
                    adapter="bottles",
                    playable_backend=None,
                ),
            ),
        )

        selections, warnings = self.service.state_selections(
            self.collection,
            game,
        )
        self.assertEqual(warnings, ())
        self.assertEqual(len(selections), 1)
        self.assertEqual(selections[0].save_set_id, "main")
        self.assertEqual(selections[0].backup.path, backup.resolve())

        request = self.request(
            backend="umu",
            state_backup=selections[0].backup.path,
            save_set_id=selections[0].save_set_id,
        )
        self.assertIsNone(request.source_profile_id)

    def test_state_selections_are_newest_first_and_classified(
        self,
    ) -> None:
        root = (
            self.collection
            / "03_PERSISTENT_STATE/example-game/history"
        )
        older = root / "older"
        newer = root / "newer"
        identity = root / "identity"
        for path in (older, newer, identity):
            path.mkdir(parents=True)

        (older / "state-backup.json").write_text(
            json.dumps(
                {
                    "created_at": "2026-07-18T14:00:00+00:00",
                    "items": [
                        {
                            "kind": "save",
                            "present": True,
                            "file_count": 1,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (newer / "state-backup.json").write_text(
            json.dumps(
                {
                    "created_at": "2026-07-18T15:00:00+00:00",
                    "items": [
                        {
                            "kind": "save",
                            "present": True,
                            "file_count": 1,
                        },
                        {
                            "kind": "identity",
                            "present": True,
                            "file_count": 1,
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        (identity / "state-backup.json").write_text(
            json.dumps(
                {
                    "created_at": "2026-07-18T13:00:00+00:00",
                    "items": [
                        {
                            "kind": "identity",
                            "present": True,
                            "file_count": 1,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        game = GameRecord(
            capsule_id="example-game",
            title="Example",
            capsule_path=self.capsule,
            source_profiles=(),
        )
        selections, warnings = self.service.state_selections(
            self.collection,
            game,
        )

        self.assertEqual(warnings, ())
        self.assertEqual(
            [item.backup.path.name for item in selections],
            ["newer", "older", "identity"],
        )
        self.assertEqual(
            selections[0].backup.present_save_count,
            1,
        )
        self.assertEqual(
            selections[2].backup.content_label,
            "Identity only — no saved game",
        )
        self.assertTrue(
            selections[0].display_name.startswith(
                selections[0].backup.display_date
            )
        )

    def test_rejects_destination_inside_collection(self) -> None:
        request = CompositionRequest(
            collection_root=self.collection,
            capsule_path=self.capsule,
            backend="direct-wine",
            runner_id="runner",
            destination=self.collection / "derived",
        )
        with self.assertRaisesRegex(
            ServiceError,
            "outside",
        ):
            self.service.compose(request)

    def test_rejects_non_directory_state_backup_for_every_backend(
        self,
    ) -> None:
        invalid = self.root / "state-backup.json"
        invalid.write_text("{}", encoding="utf-8")

        for backend in (
            "bottles",
            "direct-wine",
            "umu",
        ):
            with self.subTest(backend=backend):
                with self.assertRaisesRegex(
                    ServiceError,
                    "not a regular directory",
                ):
                    self.service.compose(
                        self.request(
                            backend=backend,
                            state_backup=invalid,
                        )
                    )

    def test_rejects_save_set_without_backup(self) -> None:
        with self.assertRaisesRegex(
            ServiceError,
            "no usable",
        ):
            self.service.compose(
                self.request(save_set_id="main")
            )

    def test_generated_operation_must_not_be_symlink(self) -> None:
        destination = self.destination_parent / "existing"
        destination.mkdir()
        target = destination / "real.sh"
        target.write_text("#!/bin/sh\n", encoding="utf-8")
        target.chmod(0o755)
        (destination / "JUGAR.sh").symlink_to("real.sh")
        with self.assertRaisesRegex(
            ServiceError,
            "unsafe",
        ):
            self.service.run_operation(
                destination,
                "play",
            )


if __name__ == "__main__":
    unittest.main()
