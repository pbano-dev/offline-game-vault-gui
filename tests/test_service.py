from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from offline_game_vault_gui.guard import resolve_destination, validate_request
from offline_game_vault_gui.model import MaterializationRequest
from offline_game_vault_gui.service import (
    _parse_json,
    execute,
    materialize,
    _stream_process,
    _validate_base_result,
    _validate_execution_payload,
    _validate_playable_result,
)

from helpers import (
    CAPSULE_ID,
    PROFILE_ID,
    SODA_RUNNER_ID,
    create_collection,
    create_playable_destination,
    runners_by_id,
    save_sets,
)


class ServiceTests(unittest.TestCase):
    def test_streams_stdout_and_stderr(self) -> None:
        records = []
        command = [
            "bash",
            "-c",
            "printf 'alpha\\n'; printf 'WARNING: beta\\n' >&2",
        ]
        returncode, stdout, stderr = _stream_process(
            command,
            os.environ.copy(),
            records.append,
        )
        self.assertEqual(returncode, 0)
        self.assertEqual(stdout, "alpha")
        self.assertTrue(stderr.endswith("WARNING: beta"))
        levels = {record.level for record in records}
        self.assertIn("STDOUT", levels)
        self.assertIn("WARNING", levels)


    def test_parses_trailing_json_after_runner_stdout(self) -> None:
        payload = _parse_json(
            "wine: preceding diagnostic\n"
            "{\n"
            '  "complete": true,\n'
            '  "game_process_rc": 0\n'
            "}\n",
            label="run-playable",
        )
        self.assertEqual(
            payload,
            {"complete": True, "game_process_rc": 0},
        )

    def test_rejects_trailing_non_whitespace_after_json(self) -> None:
        with self.assertRaisesRegex(
            Exception,
            "without returning a valid JSON object",
        ):
            _parse_json(
                '{"complete": true}\ntrailing text',
                label="run-playable",
            )

    def test_validates_base_receipt(self) -> None:
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, capsule = create_collection(base / "vault")
            parent = base / "materialized"
            parent.mkdir()
            destination = resolve_destination(
                parent,
                capsule_id=CAPSULE_ID,
                profile_id="linux-base-only",
                backend_id="base",
                runner=None,
            )
            request = validate_request(
                MaterializationRequest(
                    collection_root=root,
                    capsule_path=capsule,
                    capsule_id=CAPSULE_ID,
                    profile_id="linux-base-only",
                    backend_id="base",
                    runner=None,
                    destination=destination,
                )
            )
            request.destination.mkdir()
            receipt = request.destination / "materialization-receipt.json"
            receipt.write_text('{"complete":true}\n', encoding="utf-8")

            result = _validate_base_result(
                request,
                {
                    "complete": True,
                    "destination": str(request.destination),
                },
            )
            self.assertEqual(result, (receipt, None, None))

    def test_validates_playable_receipt_for_selected_soda(self) -> None:
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, capsule = create_collection(base / "vault")
            parent = base / "materialized"
            parent.mkdir()
            soda = runners_by_id(root)[SODA_RUNNER_ID]
            destination = resolve_destination(
                parent,
                capsule_id=CAPSULE_ID,
                profile_id=PROFILE_ID,
                backend_id="direct-wine",
                runner=soda,
            )
            request = validate_request(
                MaterializationRequest(
                    collection_root=root,
                    capsule_path=capsule,
                    capsule_id=CAPSULE_ID,
                    profile_id=PROFILE_ID,
                    backend_id="direct-wine",
                    runner=soda,
                    destination=destination,
                )
            )
            create_playable_destination(request.destination, soda)

            result = _validate_playable_result(
                request,
                {
                    "materialization": {
                        "complete": True,
                        "destination": str(request.destination),
                    }
                },
            )
            receipt, launcher, uninstaller = result
            self.assertEqual(
                receipt,
                request.destination / "playable-materialization.json",
            )
            self.assertTrue(launcher.is_file())
            self.assertTrue(uninstaller.is_file())

    def test_materialize_uses_temporary_soda_overlay(self) -> None:
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, capsule = create_collection(base / "vault")
            parent = base / "materialized"
            parent.mkdir()
            soda = runners_by_id(root)[SODA_RUNNER_ID]
            destination = resolve_destination(
                parent,
                capsule_id=CAPSULE_ID,
                profile_id=PROFILE_ID,
                backend_id="direct-wine",
                runner=soda,
            )
            request = MaterializationRequest(
                collection_root=root,
                capsule_path=capsule,
                capsule_id=CAPSULE_ID,
                profile_id=PROFILE_ID,
                backend_id="direct-wine",
                runner=soda,
                destination=destination,
            )

            observed_overlay: Path | None = None

            def fake_stream(command, _environment, _callback):
                nonlocal observed_overlay
                capsule_argument = Path(
                    command[command.index("--capsule") + 1]
                )
                state_capsule_argument = Path(
                    command[command.index("--state-capsule") + 1]
                )
                self.assertEqual(state_capsule_argument, capsule)
                self.assertIn(
                    "/usr/bin/ogv-state-capsule-bridge",
                    command,
                )
                observed_overlay = capsule_argument
                document = __import__("json").loads(
                    capsule_argument.read_text(encoding="utf-8")
                )
                profile = next(
                    item
                    for item in document["profiles"]
                    if item["id"] == PROFILE_ID
                )
                self.assertEqual(profile["status"], "not_tested")
                self.assertEqual(
                    profile["host_contract"],
                    "host-contracts/linux-direct-wine.json",
                )
                self.assertNotIn("acceptance_report", profile)
                self.assertIn(SODA_RUNNER_ID, profile["dependencies"])

                staged_contract = (
                    capsule_argument.parent
                    / "host-contracts/linux-direct-wine.json"
                )
                original_contract = (
                    capsule.parent
                    / "host-contracts/linux-direct-wine.json"
                )
                self.assertTrue(staged_contract.is_file())
                self.assertFalse(staged_contract.is_symlink())
                self.assertEqual(
                    staged_contract.read_bytes(),
                    original_contract.read_bytes(),
                )
                self.assertEqual(
                    staged_contract.stat().st_mode & 0o777,
                    0o600,
                )

                create_playable_destination(destination, soda)
                return (
                    0,
                    __import__("json").dumps(
                        {
                            "materialization": {
                                "complete": True,
                                "destination": str(destination),
                            }
                        }
                    ),
                    "",
                )

            with (
                patch(
                    "offline_game_vault_gui.service.resolve_bwrap",
                    return_value=Path("/usr/bin/true"),
                ),
                patch(
                    "offline_game_vault_gui.service.resolve_ogv",
                    return_value=Path("/usr/bin/true"),
                ),
                patch(
                    "offline_game_vault_gui.service.resolve_state_bridge",
                    return_value=Path(
                        "/usr/bin/ogv-state-capsule-bridge"
                    ),
                ),
                patch(
                    "offline_game_vault_gui.service._stream_process",
                    side_effect=fake_stream,
                ),
            ):
                outcome = materialize(request)

            self.assertEqual(outcome.runner_id, SODA_RUNNER_ID)
            self.assertIsNotNone(observed_overlay)
            assert observed_overlay is not None
            self.assertFalse(observed_overlay.exists())
            self.assertTrue(outcome.receipt_path.is_file())


    def test_materialize_with_selected_save_uses_composed_backup(self) -> None:
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, capsule = create_collection(base / "vault")
            parent = base / "materialized"
            parent.mkdir()
            runner = runners_by_id(root)["ge-proton11-1"]
            save_set = save_sets(root, capsule)[0]
            destination = resolve_destination(
                parent,
                capsule_id=CAPSULE_ID,
                profile_id=PROFILE_ID,
                backend_id="direct-wine",
                runner=runner,
                save_set_id=save_set.save_set_id,
            )
            request = MaterializationRequest(
                collection_root=root,
                capsule_path=capsule,
                capsule_id=CAPSULE_ID,
                profile_id=PROFILE_ID,
                backend_id="direct-wine",
                runner=runner,
                destination=destination,
                save_set=save_set,
            )
            observed_backup: Path | None = None

            def fake_stream(command, _environment, _callback):
                nonlocal observed_backup
                observed_backup = Path(
                    command[command.index("--state-backup") + 1]
                )
                receipt = __import__("json").loads(
                    (
                        observed_backup / "state-backup.json"
                    ).read_text(encoding="utf-8")
                )
                save_item = receipt["items"][0]
                self.assertTrue(save_item["present"])
                self.assertEqual(
                    save_item["entries"][0]["digest"],
                    save_set.digest,
                )
                create_playable_destination(destination, runner)
                return (
                    0,
                    __import__("json").dumps(
                        {
                            "materialization": {
                                "complete": True,
                                "destination": str(destination),
                            }
                        }
                    ),
                    "",
                )

            with (
                patch(
                    "offline_game_vault_gui.service.resolve_bwrap",
                    return_value=Path("/usr/bin/true"),
                ),
                patch(
                    "offline_game_vault_gui.service.resolve_ogv",
                    return_value=Path("/usr/bin/true"),
                ),
                patch(
                    "offline_game_vault_gui.service._stream_process",
                    side_effect=fake_stream,
                ),
            ):
                outcome = materialize(request)

            self.assertEqual(
                outcome.save_set_id,
                save_set.save_set_id,
            )
            self.assertIsNotNone(observed_backup)
            assert observed_backup is not None
            self.assertFalse(observed_backup.exists())
            selection = __import__("json").loads(
                (
                    destination
                    / "metadata"
                    / "ogv-gui-state-selection.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(
                selection["save_set_id"],
                save_set.save_set_id,
            )

    def test_execute_selected_soda_variant(self) -> None:
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, capsule = create_collection(base / "vault")
            parent = base / "materialized"
            parent.mkdir()
            soda = runners_by_id(root)[SODA_RUNNER_ID]
            destination = resolve_destination(
                parent,
                capsule_id=CAPSULE_ID,
                profile_id=PROFILE_ID,
                backend_id="direct-wine",
                runner=soda,
            )
            create_playable_destination(destination, soda)
            request = MaterializationRequest(
                collection_root=root,
                capsule_path=capsule,
                capsule_id=CAPSULE_ID,
                profile_id=PROFILE_ID,
                backend_id="direct-wine",
                runner=soda,
                destination=destination,
            )

            responses = [
                (
                    0,
                    __import__("json").dumps(
                        {
                            "verified": True,
                            "capsule_id": CAPSULE_ID,
                            "profile_id": PROFILE_ID,
                            "backend": "wine",
                            "destination": str(destination),
                        }
                    ),
                    "",
                ),
                (
                    0,
                    "wine: runner output\n"
                    + __import__("json").dumps(
                        {
                            "schema": 0,
                            "capsule_id": CAPSULE_ID,
                            "profile_id": PROFILE_ID,
                            "backend": "wine",
                            "destination": str(destination),
                            "game_process_rc": 0,
                            "wineserver_wait_rc": 0,
                            "complete": True,
                        },
                        indent=2,
                    ),
                    "",
                ),
            ]

            with (
                patch(
                    "offline_game_vault_gui.service.resolve_ogv",
                    return_value=Path("/usr/bin/true"),
                ),
                patch(
                    "offline_game_vault_gui.service._stream_process",
                    side_effect=responses,
                ),
            ):
                outcome = execute(request)

            self.assertEqual(outcome.runner_id, SODA_RUNNER_ID)
            self.assertEqual(outcome.game_process_rc, 0)
            self.assertTrue(outcome.complete)

    def test_execution_payload_is_bound_to_selection(self) -> None:
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, capsule = create_collection(base / "vault")
            parent = base / "materialized"
            parent.mkdir()
            soda = runners_by_id(root)[SODA_RUNNER_ID]
            destination = resolve_destination(
                parent,
                capsule_id=CAPSULE_ID,
                profile_id=PROFILE_ID,
                backend_id="direct-wine",
                runner=soda,
            )
            create_playable_destination(destination, soda)
            request = validate_request(
                MaterializationRequest(
                    collection_root=root,
                    capsule_path=capsule,
                    capsule_id=CAPSULE_ID,
                    profile_id=PROFILE_ID,
                    backend_id="direct-wine",
                    runner=soda,
                    destination=destination,
                )
            )

            result = _validate_execution_payload(
                request,
                {
                    "schema": 0,
                    "capsule_id": CAPSULE_ID,
                    "profile_id": PROFILE_ID,
                    "backend": "wine",
                    "destination": str(destination),
                    "game_process_rc": 0,
                    "wineserver_wait_rc": 0,
                    "complete": True,
                },
            )
            self.assertEqual(result.runner_id, SODA_RUNNER_ID)
            self.assertTrue(result.complete)


if __name__ == "__main__":
    unittest.main()
