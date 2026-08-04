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
)
from offline_game_vault_gui.service import CompositionService, ServiceError


class FakeCore:
    def list_runners(self, collection_root: Path):
        del collection_root
        return (), ()

    def list_component_sets(self, collection_root: Path):
        del collection_root
        return ()

    def discover_bottles_path(self) -> Path:
        return Path("/managed/bottles")

    def compose(self, request: CompositionRequest) -> CompositionResult:
        assert request.destination is not None
        destination = request.destination
        destination.mkdir()
        for name in ("JUGAR.sh", "VERIFICAR.sh", "DESINSTALAR.sh"):
            script = destination / name
            script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
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
                }
            ),
            encoding="utf-8",
        )
        self.capsule = capsule
        self.destination_parent = self.root / "derived"
        self.destination_parent.mkdir()
        self.state_backup = self.root / "state-backup"
        self.state_backup.mkdir()
        self.service = CompositionService(FakeCore())  # type: ignore[arg-type]

    def request(
        self,
        *,
        backend: str = "direct-wine",
        state_backup: Path | None = None,
        save_set_id: str | None = None,
    ) -> CompositionRequest:
        return CompositionRequest(
            collection_root=self.collection,
            capsule_path=self.capsule,
            backend=backend,  # type: ignore[arg-type]
            runner_id="runner",
            destination=self.destination_parent / "example",
            state_backup=state_backup,
            save_set_id=save_set_id,
        )

    def test_materializes_and_validates_generated_operations(self) -> None:
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
            (state_home / "offline-game-vault-gui/operations").glob("*.json")
        )
        self.assertEqual(len(receipts), 1)
        document = json.loads(receipts[0].read_text(encoding="utf-8"))
        self.assertEqual(document["request"]["save_set_id"], "main")
        self.assertTrue(document["request"]["state_backup_selected"])
        self.assertNotIn(str(self.state_backup), receipts[0].read_text())

    def test_rejects_destination_inside_collection(self) -> None:
        request = self.request()
        request = CompositionRequest(
            collection_root=request.collection_root,
            capsule_path=request.capsule_path,
            backend=request.backend,
            runner_id=request.runner_id,
            destination=self.collection / "derived",
        )
        with self.assertRaisesRegex(ServiceError, "outside"):
            self.service.compose(request)

    def test_rejects_state_backup_for_umu(self) -> None:
        request = self.request(
            backend="umu",
            state_backup=self.state_backup,
        )
        with self.assertRaisesRegex(ServiceError, "Direct-Wine"):
            self.service.compose(request)

    def test_rejects_save_set_without_backup(self) -> None:
        request = self.request(save_set_id="main")
        with self.assertRaisesRegex(ServiceError, "no usable"):
            self.service.compose(request)

    def test_generated_operation_must_not_be_symlink(self) -> None:
        destination = self.destination_parent / "existing"
        destination.mkdir()
        target = destination / "real.sh"
        target.write_text("#!/bin/sh\n", encoding="utf-8")
        target.chmod(0o755)
        (destination / "JUGAR.sh").symlink_to("real.sh")
        with self.assertRaisesRegex(ServiceError, "unsafe"):
            self.service.run_operation(destination, "play")


if __name__ == "__main__":
    unittest.main()
