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

    def test_probe_requires_0_19_7_and_commands(self) -> None:
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
                    stdout="offline-game-vault 0.19.7\n",
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

        self.assertEqual(probe.version, "0.19.7")
        self.assertIn(("compose", "--help"), calls)

    def test_probe_rejects_pre_0_19_7_core(self) -> None:
        client = self.client()
        process = subprocess.CompletedProcess(
            ["ogv"],
            0,
            stdout="offline-game-vault 0.19.6\n",
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
                destination = f"/derived/example-{backend}"
                values["destination"] = Path(destination)
                if backend == "bottles":
                    values.update(
                        bottles_path=Path("/bottles"),
                        bottle_name="example",
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
                self.assertIn("--destination", arguments)
                destination_position = arguments.index("--destination")
                self.assertEqual(
                    arguments[destination_position + 1],
                    destination,
                )
                if backend == "bottles":
                    self.assertIn(
                        "--bottle-name",
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

    def test_fresh_start_is_forwarded_for_every_backend(self) -> None:
        for backend in ("bottles", "direct-wine", "umu"):
            with self.subTest(backend=backend):
                destination = f"/derived/fresh-{backend}"
                values: dict[str, object] = {
                    "collection_root": Path("/collection"),
                    "capsule_path": Path("/collection/capsule.json"),
                    "backend": backend,
                    "runner_id": "runner",
                    "destination": Path(destination),
                    "fresh_start": True,
                }
                if backend == "bottles":
                    values["bottle_name"] = "example"
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
                self.assertEqual(arguments.count("--fresh-start"), 1)
                self.assertNotIn("--no-state", arguments)
                self.assertNotIn("--state-backup", arguments)

    def test_fresh_start_rejects_other_state_modes(self) -> None:
        common: dict[str, object] = {
            "collection_root": Path("/collection"),
            "capsule_path": Path("/collection/capsule.json"),
            "backend": "umu",
            "runner_id": "runner",
            "destination": Path("/derived/example"),
            "fresh_start": True,
        }
        for extra in (
            {"no_state": True},
            {"state_backup": Path("/collection/state-backup")},
            {"umu_save_id": "slot-a"},
        ):
            with self.subTest(extra=extra):
                request = CompositionRequest(
                    **(common | extra)  # type: ignore[arg-type]
                )
                with self.assertRaisesRegex(
                    CoreError,
                    "--fresh-start",
                ):
                    self.client().compose(request)

    def test_no_state_is_forwarded_for_every_backend(self) -> None:
        for backend in ("bottles", "direct-wine", "umu"):
            with self.subTest(backend=backend):
                destination = f"/derived/example-{backend}"
                values: dict[str, object] = {
                    "collection_root": Path("/collection"),
                    "capsule_path": Path("/collection/capsule.json"),
                    "backend": backend,
                    "runner_id": "runner",
                    "destination": Path(destination),
                    "no_state": True,
                }
                if backend == "bottles":
                    values["bottle_name"] = "example"
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
                self.assertEqual(arguments.count("--no-state"), 1)
                self.assertNotIn("--state-backup", arguments)

    def test_no_state_rejects_state_backup(self) -> None:
        request = CompositionRequest(
            collection_root=Path("/collection"),
            capsule_path=Path("/collection/capsule.json"),
            backend="umu",
            runner_id="runner",
            destination=Path("/derived/example"),
            state_backup=Path("/collection/state-backup"),
            no_state=True,
        )
        with self.assertRaisesRegex(CoreError, "mutually exclusive"):
            self.client().compose(request)

    def test_umu_save_id_is_forwarded(self) -> None:
        request = CompositionRequest(
            collection_root=Path("/collection"),
            capsule_path=Path("/collection/capsule.json"),
            backend="umu",
            runner_id="runner",
            destination=Path("/derived/example"),
            umu_save_id="slot-a",
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
        arguments = run_json.call_args.args[0]
        position = arguments.index("--save-id")
        self.assertEqual(arguments[position + 1], "slot-a")
        self.assertNotIn("--no-state", arguments)

    def test_umu_save_id_rejects_non_umu_backend(self) -> None:
        request = CompositionRequest(
            collection_root=Path("/collection"),
            capsule_path=Path("/collection/capsule.json"),
            backend="direct-wine",
            runner_id="runner",
            destination=Path("/derived/example"),
            umu_save_id="slot-a",
        )
        with self.assertRaisesRegex(CoreError, "only supported"):
            self.client().compose(request)

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
            destination=Path("/derived/example-bottles"),
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
