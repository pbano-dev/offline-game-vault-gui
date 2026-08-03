from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from offline_game_vault_gui.core import CoreClient, CoreError
from offline_game_vault_gui.model import (
    CompositionRequest,
    CompositionResult,
    RunnerRecord,
)


class CoreClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.fake_core = Path(__file__).with_name("fake_core.py")
        self.log = self.root / "commands.jsonl"
        self.bottles = self.root / "bottles"
        self.bottles.mkdir()
        environment = dict(os.environ)
        environment["FAKE_CORE_LOG"] = str(self.log)
        environment["FAKE_BOTTLES_PATH"] = str(self.bottles)
        self.client = CoreClient(
            command=(str(self.fake_core),),
            environment=environment,
            description="synthetic",
        )
        self.collection = self.root / "vault"
        self.collection.mkdir()
        self.capsule = self.collection / "capsule.json"
        self.capsule.write_text("{}", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def commands(self) -> list[list[str]]:
        if not self.log.exists():
            return []
        return [
            json.loads(line)
            for line in self.log.read_text(encoding="utf-8").splitlines()
        ]

    def test_rejects_unknown_result_schema(self) -> None:
        with self.assertRaisesRegex(ValueError, "schema"):
            CompositionResult.from_dict(
                {
                    "schema": 1,
                    "capsule_id": "game",
                    "backend": "umu",
                    "runner_id": "runner",
                    "profile_id": "profile",
                    "destination": "/tmp/output",
                    "materialized": True,
                    "played": False,
                    "play_complete": None,
                    "backend_result": {},
                }
            )

    def test_accepts_core_runner_identifier_contract(self) -> None:
        base = {
            "digest": "sha256:" + "a" * 64,
            "archive_path": "objects/runner.tar.zst",
            "size": 1,
            "format": "tar.zst",
            "source_root": "Proton-9.0-203",
            "wine_path": "files/bin/wine",
            "wineserver_path": "files/bin/wineserver",
            "compatible_backends": [
                "direct-wine",
                "bottles",
                "umu",
            ],
            "metadata_source": "synthetic",
            "proton_path": "proton",
            "kind": "proton",
        }

        for runner_id in (
            "Proton-9.0-203",
            "GE-Proton11-1",
            "wine.runner_1",
            "A" * 128,
        ):
            with self.subTest(valid=runner_id):
                value = dict(base)
                value["runner_id"] = runner_id
                self.assertEqual(
                    RunnerRecord.from_dict(value).runner_id,
                    runner_id,
                )

        for runner_id in (
            "-runner",
            "runner/name",
            "runner name",
            "A" * 129,
        ):
            with self.subTest(invalid=runner_id):
                value = dict(base)
                value["runner_id"] = runner_id
                with self.assertRaisesRegex(
                    ValueError,
                    "portable identifier",
                ):
                    RunnerRecord.from_dict(value)

    def test_rejects_unknown_runner_backend(self) -> None:
        with self.assertRaisesRegex(ValueError, "known backends"):
            RunnerRecord.from_dict(
                {
                    "runner_id": "runner",
                    "digest": "sha256:" + "a" * 64,
                    "archive_path": "objects/runner.tar.zst",
                    "size": 1,
                    "format": "tar.zst",
                    "source_root": "runner",
                    "wine_path": "bin/wine",
                    "wineserver_path": "bin/wineserver",
                    "compatible_backends": ["unknown"],
                    "metadata_source": "synthetic",
                    "proton_path": None,
                    "kind": "wine",
                }
            )

    def test_probe_requires_core_0_11_4_and_commands(self) -> None:
        result = self.client.probe()
        self.assertEqual(result.version, "0.11.4")
        self.assertEqual(
            self.commands(),
            [
                ["--version"],
                ["discover-bottles-path", "--help"],
                ["list-preserved-runners", "--help"],
                ["list-shared-umu-runtimes", "--help"],
                ["compose", "--help"],
            ],
        )

    def test_parses_global_runner_and_component_catalogs(self) -> None:
        runners, warnings = self.client.list_runners(self.collection)
        self.assertEqual(len(runners), 2)
        self.assertEqual(warnings, ("synthetic warning",))
        self.assertFalse(runners[0].supports("umu"))
        self.assertTrue(runners[1].supports("umu"))

        components = self.client.list_component_sets(self.collection)
        self.assertEqual(len(components), 1)
        self.assertEqual(
            components[0].backend_component_id,
            "umu-backend",
        )
        self.assertEqual(
            components[0].runtime_component_id,
            "steamrt4-runtime",
        )
        self.assertFalse(
            hasattr(components[0], "shared_runtime_id")
        )

    def test_discovers_managed_bottles_path(self) -> None:
        self.assertEqual(
            self.client.discover_bottles_path(),
            self.bottles,
        )

    def test_builds_exact_direct_wine_compose_command(self) -> None:
        destination = self.root / "direct"
        result = self.client.compose(
            CompositionRequest(
                collection_root=self.collection,
                capsule_path=self.capsule,
                backend="direct-wine",
                runner_id="wine-runner",
                source_profile_id="source",
                destination=destination,
                state_backup=self.root / "state.tar.zst",
                play=True,
                arguments=("-windowed",),
            )
        )
        self.assertEqual(result.destination, destination)
        self.assertTrue(result.play_complete)
        command = self.commands()[-1]
        self.assertEqual(command[0], "compose")
        self.assertIn("--source-profile", command)
        self.assertIn("--state-backup", command)
        self.assertIn("--play", command)
        self.assertEqual(command[-2:], ["--", "-windowed"])

    def test_builds_exact_umu_compose_command(self) -> None:
        destination = self.root / "umu"
        result = self.client.compose(
            CompositionRequest(
                collection_root=self.collection,
                capsule_path=self.capsule,
                backend="umu",
                runner_id="Proton-9.0-203",
                destination=destination,
            )
        )
        command = self.commands()[-1]
        self.assertIsNone(result.play_complete)
        self.assertIn("umu", command)
        self.assertNotIn("--component-set", command)
        self.assertEqual(
            result.backend_result["component_set_id"],
            "umu-component-set-test",
        )

    def test_builds_exact_bottles_compose_command(self) -> None:
        result = self.client.compose(
            CompositionRequest(
                collection_root=self.collection,
                capsule_path=self.capsule,
                backend="bottles",
                runner_id="wine-runner",
                bottles_path=self.bottles,
                bottle_name="game-bottle",
            )
        )
        self.assertEqual(
            result.destination,
            self.bottles / "game-bottle",
        )
        command = self.commands()[-1]
        self.assertIn("--bottles-path", command)
        self.assertIn("--bottle-name", command)
        self.assertNotIn("--destination", command)

    def test_rejects_bottles_game_arguments(self) -> None:
        with self.assertRaises(CoreError):
            self.client.compose(
                CompositionRequest(
                    collection_root=self.collection,
                    capsule_path=self.capsule,
                    backend="bottles",
                    runner_id="wine-runner",
                    bottle_name="game",
                    arguments=("-windowed",),
                )
            )


if __name__ == "__main__":
    unittest.main()
