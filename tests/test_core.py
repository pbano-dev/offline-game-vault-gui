from __future__ import annotations

from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from offline_game_vault_gui.core import CoreClient, CoreError
from offline_game_vault_gui.model import CompositionRequest


RESULT = {
    "schema": 0,
    "capsule_id": "example-game",
    "backend": "direct-wine",
    "runner_id": "GE-Proton11-1",
    "profile_id": "derived",
    "destination": "/derived/example",
    "materialized": True,
    "played": False,
    "play_complete": None,
    "backend_result": {},
}


class CoreClientTests(unittest.TestCase):
    def client(self) -> CoreClient:
        return CoreClient(
            command=("ogv",),
            environment={},
            description="test",
        )

    def test_probe_requires_0_11_4_and_commands(self) -> None:
        client = self.client()
        calls: list[tuple[str, ...]] = []

        def fake_run(
            arguments: tuple[str, ...],
            *,
            timeout: int,
        ) -> subprocess.CompletedProcess[str]:
            del timeout
            calls.append(arguments)
            if arguments == ("--version",):
                return subprocess.CompletedProcess(
                    ["ogv"],
                    0,
                    stdout="offline-game-vault 0.11.4\n",
                    stderr="",
                )
            return subprocess.CompletedProcess(
                ["ogv"],
                0,
                stdout="help\n",
                stderr="",
            )

        with patch.object(CoreClient, "_run", side_effect=fake_run):
            probe = client.probe()
        self.assertEqual(probe.version, "0.11.4")
        self.assertIn(("compose", "--help"), calls)

    def test_probe_rejects_old_core(self) -> None:
        client = self.client()
        process = subprocess.CompletedProcess(
            ["ogv"],
            0,
            stdout="offline-game-vault 0.11.3\n",
            stderr="",
        )
        with patch.object(CoreClient, "_run", return_value=process):
            with self.assertRaisesRegex(CoreError, "too old"):
                client.probe()

    def test_direct_wine_command_includes_selected_state_backup(self) -> None:
        client = self.client()
        request = CompositionRequest(
            collection_root=Path("/collection"),
            capsule_path=Path("/collection/02_CAPSULES/example/capsule.json"),
            backend="direct-wine",
            runner_id="GE-Proton11-1",
            source_profile_id="source",
            destination=Path("/derived/example"),
            state_backup=Path("/collection/03_PERSISTENT_STATE/backup"),
            save_set_id="main",
            play=True,
            arguments=("--difficulty", "hard"),
        )
        with patch.object(
            CoreClient,
            "run_json",
            return_value=RESULT | {"played": True, "play_complete": True},
        ) as run_json:
            client.compose(request)
        arguments = run_json.call_args.args[0]
        self.assertEqual(
            arguments[:7],
            [
                "compose",
                "--collection-root",
                "/collection",
                "--capsule",
                "/collection/02_CAPSULES/example/capsule.json",
                "--backend",
                "direct-wine",
            ],
        )
        self.assertIn("--state-backup", arguments)
        self.assertIn("/collection/03_PERSISTENT_STATE/backup", arguments)
        self.assertIn("--play", arguments)
        self.assertEqual(arguments[-3:], ["--", "--difficulty", "hard"])

    def test_bottles_rejects_additional_arguments(self) -> None:
        client = self.client()
        request = CompositionRequest(
            collection_root=Path("/collection"),
            capsule_path=Path("/collection/capsule.json"),
            backend="bottles",
            runner_id="runner",
            bottles_path=Path("/bottles"),
            bottle_name="example",
            arguments=("--flag",),
        )
        with self.assertRaisesRegex(CoreError, "not supported"):
            client.compose(request)


if __name__ == "__main__":
    unittest.main()
