from __future__ import annotations

import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from offline_game_vault_gui.bottles_backend import BottlesEnvironment
from offline_game_vault_gui.guard import (
    bottle_deployment_name,
    resolve_destination,
    validate_request,
)
from offline_game_vault_gui.model import MaterializationRequest
from offline_game_vault_gui.sandbox import (
    build_deploy_bottles_command,
    build_run_bottles_command,
    build_verify_bottles_command,
)
from offline_game_vault_gui.service import (
    MaterializationError,
    execute,
    materialize,
)

from helpers import (
    BOTTLES_PROFILE_ID,
    CAPSULE_ID,
    SODA_RUNNER_ID,
    create_base_destination,
    create_bottles_deployment,
    create_collection,
    runners_by_id,
    bottles_backend,
    BOTTLES_APP_REF,
    BOTTLES_APP_COMMIT,
)


class BottlesFlowTests(unittest.TestCase):
    def _request(
        self,
        base: Path,
        *,
        create_source: bool,
        create_deployment: bool,
    ) -> tuple[MaterializationRequest, Path, Path, object]:
        root, capsule = create_collection(base / "vault")
        parent = base / "materialized"
        parent.mkdir()
        bottles_path = base / "bottles"
        bottles_path.mkdir()
        soda = runners_by_id(root)[SODA_RUNNER_ID]
        destination = resolve_destination(
            parent,
            capsule_id=CAPSULE_ID,
            profile_id=BOTTLES_PROFILE_ID,
            backend_id="bottles",
            runner=soda,
        )
        if create_source:
            create_base_destination(destination)
        bottle_name = bottle_deployment_name(
            CAPSULE_ID,
            BOTTLES_PROFILE_ID,
            SODA_RUNNER_ID,
        )
        if create_deployment:
            create_bottles_deployment(
                bottles_path,
                bottle_name=bottle_name,
                runner_id=SODA_RUNNER_ID,
            )
        request = MaterializationRequest(
            collection_root=root,
            capsule_path=capsule,
            capsule_id=CAPSULE_ID,
            profile_id=BOTTLES_PROFILE_ID,
            backend_id="bottles",
            runner=soda,
            destination=destination,
            bottles_path=bottles_path,
            bottles_backend=bottles_backend(root),
        )
        return request, bottles_path, destination, soda

    def test_guard_binds_source_deployment_and_runner(self) -> None:
        with TemporaryDirectory() as temporary:
            request, bottles_path, destination, _soda = self._request(
                Path(temporary),
                create_source=True,
                create_deployment=False,
            )
            validated = validate_request(request)
            self.assertEqual(validated.backend_id, "bottles")
            self.assertEqual(validated.mode, "base")
            self.assertTrue(validated.source_reusable)
            self.assertFalse(validated.reusable)
            self.assertTrue(validated.overlay_required)
            self.assertEqual(validated.bottles_path, bottles_path)
            self.assertEqual(validated.destination, destination)
            self.assertEqual(
                validated.deployment_path,
                bottles_path / validated.bottle_name,
            )

    def test_bottles_sandbox_commands(self) -> None:
        with TemporaryDirectory() as temporary:
            request, bottles_path, _destination, _soda = self._request(
                Path(temporary),
                create_source=False,
                create_deployment=False,
            )
            validated = validate_request(request)
            deploy = build_deploy_bottles_command(
                validated,
                bwrap=Path("/usr/bin/bwrap"),
                ogv=Path("/usr/bin/ogv"),
            )
            self.assertIn("--unshare-net", deploy)
            self.assertEqual(
                deploy[deploy.index("--bottles-path") + 1],
                str(bottles_path),
            )
            self.assertEqual(
                deploy[deploy.index("--name") + 1],
                validated.bottle_name,
            )
            self.assertEqual(
                build_verify_bottles_command(
                    bottles_path,
                    validated.bottle_name,
                    ogv=Path("/usr/bin/ogv"),
                )[:2],
                ["/usr/bin/ogv", "verify-bottles-deployment"],
            )
            self.assertEqual(
                build_run_bottles_command(
                    bottles_path,
                    validated.bottle_name,
                    ogv=Path("/usr/bin/ogv"),
                )[:2],
                ["/usr/bin/ogv", "run-bottles"],
            )

    def test_rejects_installed_flatpak_commit_mismatch(self) -> None:
        with TemporaryDirectory() as temporary:
            request, bottles_path, _destination, _soda = self._request(
                Path(temporary),
                create_source=True,
                create_deployment=False,
            )
            environment = BottlesEnvironment(
                bottles_path=bottles_path,
                installed_runners=frozenset({SODA_RUNNER_ID}),
                flatpak=Path("/usr/bin/flatpak"),
                application_ref=BOTTLES_APP_REF,
                application_commit="c" * 64,
            )
            with patch(
                "offline_game_vault_gui.service.scan_bottles_environment",
                return_value=environment,
            ):
                with self.assertRaises(MaterializationError):
                    materialize(request)

    def test_materialize_deploys_selected_runner_and_restores_source(self) -> None:
        with TemporaryDirectory() as temporary:
            request, bottles_path, destination, soda = self._request(
                Path(temporary),
                create_source=True,
                create_deployment=False,
            )
            validated = validate_request(request)
            assert validated.bottle_name is not None
            source_yml = (
                destination / "objects/baseline/Game/bottle.yml"
            )
            original = source_yml.read_bytes()
            environment = BottlesEnvironment(
                bottles_path=bottles_path,
                installed_runners=frozenset({SODA_RUNNER_ID}),
                flatpak=Path("/usr/bin/flatpak"),
                application_ref=BOTTLES_APP_REF,
                application_commit=BOTTLES_APP_COMMIT,
            )
            calls: list[str] = []

            def fake_stream(command, _environment, _callback):
                operation = command[-1] if command[-1] != "--json" else ""
                if "restore-state" in command:
                    calls.append("restore")
                    return (
                        0,
                        json.dumps(
                            {
                                "complete": True,
                                "capsule_id": CAPSULE_ID,
                                "rollback_performed": False,
                                "restored_count": 1,
                                "missing_count": 1,
                            }
                        ),
                        "",
                    )
                if "restore-state" in command:
                    calls.append("restore")
                    return (
                        0,
                        json.dumps(
                            {
                                "complete": True,
                                "capsule_id": CAPSULE_ID,
                                "rollback_performed": False,
                                "restored_count": 1,
                                "missing_count": 1,
                            }
                        ),
                        "",
                    )
                if "deploy-bottles" in command:
                    calls.append("deploy")
                    self.assertIn(
                        'Runner: "soda-9.0-1"',
                        source_yml.read_text(encoding="utf-8"),
                    )
                    evidence = (
                        source_yml.parent
                        / ".ogv-gui-runner-selection.json"
                    )
                    self.assertTrue(evidence.is_file())
                    create_bottles_deployment(
                        bottles_path,
                        bottle_name=validated.bottle_name,
                        runner_id=SODA_RUNNER_ID,
                    )
                    copied = (
                        bottles_path
                        / validated.bottle_name
                        / ".ogv-gui-runner-selection.json"
                    )
                    copied.write_bytes(evidence.read_bytes())
                    return (
                        0,
                        json.dumps(
                            {
                                "complete": True,
                                "capsule_id": CAPSULE_ID,
                                "profile_id": BOTTLES_PROFILE_ID,
                                "bottle_name": validated.bottle_name,
                                "runner": SODA_RUNNER_ID,
                            }
                        ),
                        "",
                    )
                if "verify-bottles-deployment" in command:
                    calls.append("verify")
                    return (
                        0,
                        json.dumps(
                            {
                                "verified": True,
                                "capsule_id": CAPSULE_ID,
                                "profile_id": BOTTLES_PROFILE_ID,
                                "bottle_name": validated.bottle_name,
                                "runner": SODA_RUNNER_ID,
                            }
                        ),
                        "",
                    )
                if "remove-materialization" in command:
                    calls.append("remove")
                    shutil.rmtree(destination)
                    return (
                        0,
                        json.dumps(
                            {
                                "removed": True,
                                "capsule_id": CAPSULE_ID,
                                "profile_id": BOTTLES_PROFILE_ID,
                            }
                        ),
                        "",
                    )
                self.fail(f"Unexpected operation: {command}")

            with (
                patch(
                    "offline_game_vault_gui.service.scan_bottles_environment",
                    return_value=environment,
                ),
                patch(
                    "offline_game_vault_gui.service.resolve_bwrap",
                    return_value=Path("/usr/bin/bwrap"),
                ),
                patch(
                    "offline_game_vault_gui.service.resolve_ogv",
                    return_value=Path("/usr/bin/ogv"),
                ),
                patch(
                    "offline_game_vault_gui.service._stream_process",
                    side_effect=fake_stream,
                ),
            ):
                outcome = materialize(request)

            self.assertEqual(calls, ["restore", "deploy", "verify", "remove"])
            self.assertEqual(outcome.backend_id, "bottles")
            self.assertEqual(outcome.runner_id, SODA_RUNNER_ID)
            self.assertFalse(source_yml.exists())
            self.assertTrue(outcome.receipt_path.is_file())
            self.assertTrue(outcome.launcher_path.is_file())
            self.assertTrue(outcome.uninstaller_path.is_file())
            self.assertTrue(outcome.payload["single_copy"])
            assert outcome.deployment_path is not None
            evidence = (
                outcome.deployment_path
                / ".ogv-gui-runner-selection.json"
            )
            self.assertTrue(evidence.is_file())
            self.assertFalse(
                json.loads(evidence.read_text(encoding="utf-8"))[
                    "acceptance_transferred"
                ]
            )

    def test_fresh_bottles_flow_leaves_only_managed_heavy_copy(self) -> None:
        with TemporaryDirectory() as temporary:
            request, bottles_path, destination, _soda = self._request(
                Path(temporary),
                create_source=False,
                create_deployment=False,
            )
            validated = validate_request(request)
            environment = BottlesEnvironment(
                bottles_path=bottles_path,
                installed_runners=frozenset({SODA_RUNNER_ID}),
                flatpak=Path("/usr/bin/flatpak"),
                application_ref=BOTTLES_APP_REF,
                application_commit=BOTTLES_APP_COMMIT,
            )
            calls: list[str] = []

            def fake_stream(command, _environment, _callback):
                if "materialize" in command:
                    calls.append("materialize")
                    create_base_destination(destination)
                    return (
                        0,
                        json.dumps(
                            {
                                "complete": True,
                                "capsule_id": CAPSULE_ID,
                                "profile_id": BOTTLES_PROFILE_ID,
                                "destination": str(destination),
                            }
                        ),
                        "",
                    )
                if "restore-state" in command:
                    calls.append("restore")
                    return (
                        0,
                        json.dumps(
                            {
                                "complete": True,
                                "capsule_id": CAPSULE_ID,
                                "rollback_performed": False,
                                "restored_count": 1,
                                "missing_count": 1,
                            }
                        ),
                        "",
                    )
                if "deploy-bottles" in command:
                    calls.append("deploy")
                    create_bottles_deployment(
                        bottles_path,
                        bottle_name=validated.bottle_name,
                        runner_id=SODA_RUNNER_ID,
                    )
                    return (
                        0,
                        json.dumps(
                            {
                                "complete": True,
                                "capsule_id": CAPSULE_ID,
                                "profile_id": BOTTLES_PROFILE_ID,
                                "bottle_name": validated.bottle_name,
                                "runner": SODA_RUNNER_ID,
                            }
                        ),
                        "",
                    )
                if "verify-bottles-deployment" in command:
                    calls.append("verify")
                    return (
                        0,
                        json.dumps(
                            {
                                "verified": True,
                                "capsule_id": CAPSULE_ID,
                                "profile_id": BOTTLES_PROFILE_ID,
                                "bottle_name": validated.bottle_name,
                                "runner": SODA_RUNNER_ID,
                            }
                        ),
                        "",
                    )
                if "remove-materialization" in command:
                    calls.append("remove")
                    shutil.rmtree(destination)
                    return (
                        0,
                        json.dumps(
                            {
                                "removed": True,
                                "capsule_id": CAPSULE_ID,
                                "profile_id": BOTTLES_PROFILE_ID,
                            }
                        ),
                        "",
                    )
                self.fail(f"Unexpected operation: {command}")

            with (
                patch(
                    "offline_game_vault_gui.service.scan_bottles_environment",
                    return_value=environment,
                ),
                patch(
                    "offline_game_vault_gui.service.resolve_bwrap",
                    return_value=Path("/usr/bin/bwrap"),
                ),
                patch(
                    "offline_game_vault_gui.service.resolve_ogv",
                    return_value=Path("/usr/bin/ogv"),
                ),
                patch(
                    "offline_game_vault_gui.service._stream_process",
                    side_effect=fake_stream,
                ),
            ):
                outcome = materialize(request)

            self.assertEqual(
                calls,
                ["materialize", "restore", "deploy", "verify", "remove"],
            )
            self.assertTrue(outcome.payload["single_copy"])
            self.assertTrue(validated.deployment_path.is_dir())
            self.assertTrue(outcome.receipt_path.is_file())
            self.assertEqual(
                {path.name for path in destination.iterdir()},
                {
                    outcome.receipt_path.name,
                    outcome.launcher_path.name,
                    outcome.uninstaller_path.name,
                    ".ogv-gui-state-selection.json",
                },
            )

    def test_migrates_0109_duplicate_to_single_copy_control(self) -> None:
        with TemporaryDirectory() as temporary:
            request, bottles_path, destination, _soda = self._request(
                Path(temporary),
                create_source=True,
                create_deployment=True,
            )
            validated = validate_request(request)
            environment = BottlesEnvironment(
                bottles_path=bottles_path,
                installed_runners=frozenset({SODA_RUNNER_ID}),
                flatpak=Path("/usr/bin/flatpak"),
                application_ref=BOTTLES_APP_REF,
                application_commit=BOTTLES_APP_COMMIT,
            )
            calls: list[str] = []

            def fake_stream(command, _environment, _callback):
                if "verify-bottles-deployment" in command:
                    calls.append("verify")
                    return (
                        0,
                        json.dumps(
                            {
                                "verified": True,
                                "capsule_id": CAPSULE_ID,
                                "profile_id": BOTTLES_PROFILE_ID,
                                "bottle_name": validated.bottle_name,
                                "runner": SODA_RUNNER_ID,
                            }
                        ),
                        "",
                    )
                if "restore-state" in command:
                    calls.append("restore")
                    return (
                        0,
                        json.dumps(
                            {
                                "complete": True,
                                "capsule_id": CAPSULE_ID,
                                "rollback_performed": False,
                                "restored_count": 0,
                                "missing_count": 1,
                            }
                        ),
                        "",
                    )
                if "remove-materialization" in command:
                    calls.append("remove")
                    shutil.rmtree(destination)
                    return (
                        0,
                        json.dumps(
                            {
                                "removed": True,
                                "capsule_id": CAPSULE_ID,
                                "profile_id": BOTTLES_PROFILE_ID,
                            }
                        ),
                        "",
                    )
                self.fail(f"Unexpected operation: {command}")

            with (
                patch(
                    "offline_game_vault_gui.service.scan_bottles_environment",
                    return_value=environment,
                ),
                patch(
                    "offline_game_vault_gui.service.resolve_bwrap",
                    return_value=Path("/usr/bin/bwrap"),
                ),
                patch(
                    "offline_game_vault_gui.service.resolve_ogv",
                    return_value=Path("/usr/bin/ogv"),
                ),
                patch(
                    "offline_game_vault_gui.service._stream_process",
                    side_effect=fake_stream,
                ),
            ):
                outcome = materialize(request)

            self.assertEqual(calls, ["verify", "restore", "verify", "remove"])
            self.assertTrue(outcome.payload["single_copy"])
            self.assertTrue(outcome.receipt_path.is_file())
            self.assertTrue(outcome.launcher_path.is_file())
            self.assertTrue(outcome.uninstaller_path.is_file())
            self.assertTrue(validated.deployment_path.is_dir())
            self.assertEqual(
                {path.name for path in destination.iterdir()},
                {
                    outcome.receipt_path.name,
                    outcome.launcher_path.name,
                    outcome.uninstaller_path.name,
                    ".ogv-gui-state-selection.json",
                },
            )

    def test_reusable_none_reconciles_legacy_bottle_and_removes_save(self) -> None:
        with TemporaryDirectory() as temporary:
            request, bottles_path, destination, _soda = self._request(
                Path(temporary),
                create_source=False,
                create_deployment=True,
            )
            validated = validate_request(request)
            assert validated.deployment_path is not None
            stale_save = (
                validated.deployment_path
                / "drive_c"
                / "save.dat"
            )
            stale_save.write_bytes(b"legacy-save\n")

            environment = BottlesEnvironment(
                bottles_path=bottles_path,
                installed_runners=frozenset({SODA_RUNNER_ID}),
                flatpak=Path("/usr/bin/flatpak"),
                application_ref=BOTTLES_APP_REF,
                application_commit=BOTTLES_APP_COMMIT,
            )
            calls: list[str] = []

            def fake_stream(command, _environment, _callback):
                if "verify-bottles-deployment" in command:
                    calls.append("verify")
                    return (
                        0,
                        json.dumps(
                            {
                                "verified": True,
                                "capsule_id": CAPSULE_ID,
                                "profile_id": BOTTLES_PROFILE_ID,
                                "bottle_name": validated.bottle_name,
                                "runner": SODA_RUNNER_ID,
                            }
                        ),
                        "",
                    )
                if "restore-state" in command:
                    calls.append("restore")
                    state_root = Path(
                        command[command.index("--state-root") + 1]
                    )
                    self.assertEqual(
                        state_root,
                        validated.deployment_path,
                    )
                    self.assertIn(str(bottles_path), command)
                    (state_root / "drive_c/save.dat").unlink()
                    return (
                        0,
                        json.dumps(
                            {
                                "complete": True,
                                "capsule_id": CAPSULE_ID,
                                "rollback_performed": False,
                                "restored_count": 0,
                                "missing_count": 1,
                            }
                        ),
                        "",
                    )
                self.fail(f"Unexpected operation: {command}")

            with (
                patch(
                    "offline_game_vault_gui.service.scan_bottles_environment",
                    return_value=environment,
                ),
                patch(
                    "offline_game_vault_gui.service.resolve_bwrap",
                    return_value=Path("/usr/bin/bwrap"),
                ),
                patch(
                    "offline_game_vault_gui.service.resolve_ogv",
                    return_value=Path("/usr/bin/ogv"),
                ),
                patch(
                    "offline_game_vault_gui.service._stream_process",
                    side_effect=fake_stream,
                ),
            ):
                outcome = materialize(request)

            self.assertEqual(calls, ["verify", "restore", "verify"])
            self.assertFalse(stale_save.exists())
            self.assertTrue(outcome.payload["state_restore"]["complete"])
            self.assertTrue(
                (
                    validated.deployment_path
                    / ".ogv-gui-state-selection.json"
                ).is_file()
            )
            self.assertTrue(destination.is_dir())

    def test_execute_bottles_verifies_before_and_after(self) -> None:
        with TemporaryDirectory() as temporary:
            request, bottles_path, _destination, _soda = self._request(
                Path(temporary),
                create_source=True,
                create_deployment=True,
            )
            validated = validate_request(request)
            assert validated.bottle_name is not None
            environment = BottlesEnvironment(
                bottles_path=bottles_path,
                installed_runners=frozenset({SODA_RUNNER_ID}),
                flatpak=Path("/usr/bin/flatpak"),
                application_ref=BOTTLES_APP_REF,
                application_commit=BOTTLES_APP_COMMIT,
            )
            responses = [
                (
                    0,
                    json.dumps(
                        {
                            "verified": True,
                            "capsule_id": CAPSULE_ID,
                            "profile_id": BOTTLES_PROFILE_ID,
                            "bottle_name": validated.bottle_name,
                            "runner": SODA_RUNNER_ID,
                        }
                    ),
                    "",
                ),
                (
                    0,
                    json.dumps(
                        {
                            "schema": 0,
                            "capsule_id": CAPSULE_ID,
                            "profile_id": BOTTLES_PROFILE_ID,
                            "bottle_name": validated.bottle_name,
                            "entrypoint": "drive_c/Games/Test/game.exe",
                            "network": "isolated",
                            "flatpak_app": "com.usebottles.bottles",
                            "command": ["flatpak", "run"],
                            "returncode": 0,
                        }
                    ),
                    "",
                ),
                (
                    0,
                    json.dumps(
                        {
                            "verified": True,
                            "capsule_id": CAPSULE_ID,
                            "profile_id": BOTTLES_PROFILE_ID,
                            "bottle_name": validated.bottle_name,
                            "runner": SODA_RUNNER_ID,
                        }
                    ),
                    "",
                ),
            ]
            with (
                patch(
                    "offline_game_vault_gui.service.scan_bottles_environment",
                    return_value=environment,
                ),
                patch(
                    "offline_game_vault_gui.service.resolve_ogv",
                    return_value=Path("/usr/bin/ogv"),
                ),
                patch(
                    "offline_game_vault_gui.service._stream_process",
                    side_effect=responses,
                ) as stream,
            ):
                outcome = execute(request)

            self.assertEqual(stream.call_count, 3)
            self.assertEqual(outcome.backend_id, "bottles")
            self.assertEqual(outcome.game_process_rc, 0)
            self.assertIsNone(outcome.wineserver_wait_rc)
            self.assertTrue(outcome.complete)


if __name__ == "__main__":
    unittest.main()
