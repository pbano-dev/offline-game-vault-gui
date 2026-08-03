from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from offline_game_vault_gui.catalog import CapsuleCatalog
from offline_game_vault_gui.core import CoreClient
from offline_game_vault_gui.model import CompositionRequest
from offline_game_vault_gui.service import CompositionService, ServiceError


class CompositionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.collection = self.root / "vault"
        capsule_directory = self.collection / "02_CAPSULES/game"
        capsule_directory.mkdir(parents=True)
        self.capsule = capsule_directory / "capsule.json"
        self.capsule.write_text(
            json.dumps(
                {
                    "capsule_id": "game",
                    "game": {"title": "Game"},
                    "profiles": [
                        {
                            "id": "source",
                            "platform": "linux",
                            "adapter": "wine",
                            "playable": {"backend": "wine"},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        self.destination_parent = self.root / "derivatives"
        self.destination_parent.mkdir()
        self.bottles = self.root / "bottles"
        self.bottles.mkdir()
        environment = dict(os.environ)
        environment["FAKE_BOTTLES_PATH"] = str(self.bottles)
        environment["FAKE_CORE_LOG"] = str(self.root / "commands.jsonl")
        environment["XDG_STATE_HOME"] = str(self.root / "state")
        self.service = CompositionService(
            CoreClient(
                command=(str(Path(__file__).with_name("fake_core.py")),),
                environment=environment,
                description="synthetic",
            ),
            CapsuleCatalog(),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_loads_games_and_filters_runners_by_backend(self) -> None:
        games, runners, warnings = self.service.load(self.collection)
        self.assertEqual(len(games), 1)
        self.assertEqual(len(runners), 2)
        self.assertEqual(warnings, ("synthetic warning",))
        umu = self.service.compatible_runners(runners, "umu")
        self.assertEqual([item.runner_id for item in umu], ["Proton-9.0-203"])

    def test_materializes_and_uses_generated_root_operations(self) -> None:
        destination = self.destination_parent / "game"
        with patch.dict(
            os.environ,
            {"XDG_STATE_HOME": str(self.root / "state")},
        ):
            result = self.service.compose(
                CompositionRequest(
                    collection_root=self.collection,
                    capsule_path=self.capsule,
                    backend="umu",
                    runner_id="Proton-9.0-203",
                    destination=destination,
                )
            )
        self.assertEqual(result.destination, destination)
        verified = self.service.run_operation(destination, "verify")
        self.assertEqual(verified.returncode, 0)
        self.assertEqual(verified.stdout.strip(), "verified")
        played = self.service.run_operation(destination, "play", ("arg",))
        self.assertEqual(played.returncode, 0)
        self.assertEqual(played.stdout.strip(), "played")
        receipts = list(
            (self.root / "state/offline-game-vault-gui/operations").glob(
                "*.json"
            )
        )
        self.assertEqual(len(receipts), 1)
        document = json.loads(receipts[0].read_text(encoding="utf-8"))
        self.assertEqual(document["backend"], "umu")
        self.assertEqual(
            document["backend_facts"]["component_set_id"],
            "umu-component-set-test",
        )
        self.assertNotIn("backend_result", document)
        self.assertNotIn("arguments", document["request"])
        self.assertEqual(document["request"]["argument_count"], 0)
        self.assertNotIn("acceptance", json.dumps(document).casefold())

    def test_rejects_destination_inside_collection(self) -> None:
        with self.assertRaisesRegex(ServiceError, "outside the collection"):
            self.service.compose(
                CompositionRequest(
                    collection_root=self.collection,
                    capsule_path=self.capsule,
                    backend="direct-wine",
                    runner_id="wine-runner",
                    destination=self.collection / "writable",
                )
            )

    def test_rejects_symlinked_generated_operation(self) -> None:
        destination = self.destination_parent / "unsafe"
        destination.mkdir()
        outside = self.root / "outside.sh"
        outside.write_text("#!/bin/sh\n", encoding="utf-8")
        outside.chmod(0o755)
        (destination / "JUGAR.sh").symlink_to(outside)
        for name in ("VERIFICAR.sh", "DESINSTALAR.sh"):
            path = destination / name
            path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            path.chmod(0o755)
        with self.assertRaisesRegex(ServiceError, "unsafe"):
            self.service.run_operation(destination, "play")

    def test_remove_passes_generated_script_arguments(self) -> None:
        destination = self.destination_parent / "ops"
        destination.mkdir()
        for name in ("JUGAR.sh", "VERIFICAR.sh", "DESINSTALAR.sh"):
            path = destination / name
            path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            path.chmod(0o755)
        result = self.service.run_operation(
            destination,
            "remove",
            ("--confirm-state-preserved",),
        )
        self.assertEqual(result.returncode, 0)


    def test_rejects_symlinked_destination_parent(self) -> None:
        real_parent = self.root / "real-parent"
        real_parent.mkdir()
        linked_parent = self.root / "linked-parent"
        linked_parent.symlink_to(real_parent, target_is_directory=True)
        with self.assertRaisesRegex(ServiceError, "parent"):
            self.service.compose(
                CompositionRequest(
                    collection_root=self.collection,
                    capsule_path=self.capsule,
                    backend="direct-wine",
                    runner_id="wine-runner",
                    destination=linked_parent / "game",
                )
            )

    def test_rejects_non_portable_bottle_name(self) -> None:
        with self.assertRaisesRegex(ServiceError, "portable"):
            self.service.compose(
                CompositionRequest(
                    collection_root=self.collection,
                    capsule_path=self.capsule,
                    backend="bottles",
                    runner_id="wine-runner",
                    bottle_name="../escape",
                    bottles_path=self.bottles,
                )
            )

    def test_direct_wine_state_backup_is_a_directory(self) -> None:
        backup = self.root / "backup"
        backup.mkdir()
        destination = self.destination_parent / "direct"
        result = self.service.compose(
            CompositionRequest(
                collection_root=self.collection,
                capsule_path=self.capsule,
                backend="direct-wine",
                runner_id="wine-runner",
                destination=destination,
                state_backup=backup,
            )
        )
        self.assertEqual(result.destination, destination)


if __name__ == "__main__":
    unittest.main()
