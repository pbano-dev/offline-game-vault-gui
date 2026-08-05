from __future__ import annotations

from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from offline_game_vault_gui.core import (
    CoreClient,
    CoreError,
)
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

    def test_probe_requires_0_12_0_and_commands(self) -> None:
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
                    stdout="offline-game-vault 0.12.2\n",
                    stderr="",
                )
            return subprocess.CompletedProcess(
                ["ogv"],
                0,
                stdout="help\n",
                stderr="",
            )

        with patch.object(
            CoreClient,
            "_run",
            side_effect=fake_run,
        ):
            probe = client.probe()

        self.assertEqual(probe.version, "0.12.2")
        self.assertIn(("compose", "--help"), calls)

    def test_probe_rejects_pre_0_12_core(self) -> None:
        client = self.client()
        process = subprocess.CompletedProcess(
            ["ogv"],
            0,
            stdout="offline-game-vault 0.11.4\n",
            stderr="",
        )
        with patch.object(
            CoreClient,
            "_run",
            return_value=process,
        ):
            with self.assertRaisesRegex(CoreError, "too old"):
                client.probe()

    def test_state_backup_is_forwarded_for_every_backend(self) -> None:
        backup = Path(
            "/collection/03_PERSISTENT_STATE/backup"
        )

        for backend in (
            "bottles",
            "direct-wine",
            "umu",
        ):
            with self.subTest(backend=backend):
                values: dict[str, object] = {
                    "collection_root": Path("/collection"),
                    "capsule_path": Path(
                        "/collection/02_CAPSULES/"
                        "example/capsule.json"
                    ),
                    "backend": backend,
                    "runner_id": "GE-Proton11-1",
                    "source_profile_id": "source",
                    "state_backup": backup,
                    "save_set_id": "main",
                }
                if backend == "bottles":
                    values.update(
                        bottles_path=Path("/bottles"),
                        bottle_name="example",
                    )
                    destination = "/bottles/example"
                else:
                    values["destination"] = Path(
                        f"/derived/example-{backend}"
                    )
                    destination = (
                        f"/derived/example-{backend}"
                    )

                request = CompositionRequest(
                    **values  # type: ignore[arg-type]
                )

                with patch.object(
                    CoreClient,
                    "run_json",
                    return_value=RESULT
                    | {
                        "backend": backend,
                        "destination": destination,
                    },
                ) as run_json:
                    self.client().compose(request)

                arguments = run_json.call_args.args[0]
                self.assertEqual(
                    arguments.count("--state-backup"),
                    1,
                )
                position = arguments.index("--state-backup")
                self.assertEqual(
                    arguments[position + 1],
                    str(backup),
                )
                if backend == "bottles":
                    self.assertIn(
                        "--bottle-name",
                        arguments,
                    )
                    self.assertNotIn(
                        "--destination",
                        arguments,
                    )
                else:
                    self.assertIn(
                        "--destination",
                        arguments,
                    )

    def test_verifies_state_backup_through_core(self) -> None:
        backup = Path("/collection/backups/main")
        capsule = Path("/collection/capsule.json")
        with patch.object(
            CoreClient,
            "run_json",
            return_value={
                "schema": 0,
                "capsule_id": "example-game",
                "backup_id": "main-backup",
                "backup_kind": "accepted",
                "item_count": 2,
                "present_count": 2,
                "missing_count": 0,
                "total_bytes": 123,
                "verified": True,
                "problems": [],
            },
        ) as run_json:
            result = self.client().verify_state_backup(
                capsule_path=capsule,
                backup=backup,
            )

        self.assertEqual(result.backup_id, "main-backup")
        self.assertEqual(result.path, backup)
        self.assertEqual(
            run_json.call_args.args[0],
            (
                "verify-state-backup",
                "--capsule",
                str(capsule),
                "--backup",
                str(backup),
                "--json",
            ),
        )

    def test_no_state_backup_is_not_invented(self) -> None:
        request = CompositionRequest(
            collection_root=Path("/collection"),
            capsule_path=Path("/collection/capsule.json"),
            backend="umu",
            runner_id="runner",
            destination=Path("/derived/example"),
        )
        with patch.object(
            CoreClient,
            "run_json",
            return_value=RESULT
            | {
                "backend": "umu",
                "destination": "/derived/example",
            },
        ) as run_json:
            self.client().compose(request)
        self.assertNotIn(
            "--state-backup",
            run_json.call_args.args[0],
        )

    def test_direct_wine_preserves_play_arguments(self) -> None:
        request = CompositionRequest(
            collection_root=Path("/collection"),
            capsule_path=Path(
                "/collection/02_CAPSULES/"
                "example/capsule.json"
            ),
            backend="direct-wine",
            runner_id="GE-Proton11-1",
            destination=Path("/derived/example"),
            state_backup=Path("/collection/state-backup"),
            play=True,
            arguments=("--difficulty", "hard"),
        )
        with patch.object(
            CoreClient,
            "run_json",
            return_value=RESULT
            | {
                "played": True,
                "play_complete": True,
            },
        ) as run_json:
            self.client().compose(request)

        arguments = run_json.call_args.args[0]
        self.assertIn("--play", arguments)
        self.assertEqual(
            arguments[-3:],
            ["--", "--difficulty", "hard"],
        )

    def test_bottles_rejects_additional_arguments(self) -> None:
        request = CompositionRequest(
            collection_root=Path("/collection"),
            capsule_path=Path("/collection/capsule.json"),
            backend="bottles",
            runner_id="runner",
            bottles_path=Path("/bottles"),
            bottle_name="example",
            arguments=("--flag",),
        )
        with self.assertRaisesRegex(
            CoreError,
            "not supported",
        ):
            self.client().compose(request)

    def test_run_json_rejects_invalid_json(self) -> None:
        process = subprocess.CompletedProcess(
            ["ogv"],
            0,
            stdout="not-json",
            stderr="",
        )
        with patch.object(
            CoreClient,
            "_run",
            return_value=process,
        ):
            with self.assertRaisesRegex(
                CoreError,
                "invalid JSON",
            ):
                self.client().run_json(("compose",))


if __name__ == "__main__":
    unittest.main()
