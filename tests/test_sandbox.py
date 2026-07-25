from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from offline_game_vault_gui.guard import resolve_destination, validate_request
from offline_game_vault_gui.model import MaterializationRequest
from offline_game_vault_gui.sandbox import (
    build_command,
    build_run_playable_command,
    build_verify_playable_command,
    build_restore_state_command,
)

from helpers import (
    CAPSULE_ID,
    PROFILE_ID,
    SODA_RUNNER_ID,
    create_collection,
    runners_by_id,
)


class SandboxTests(unittest.TestCase):
    def _validated(
        self,
        root: Path,
        capsule: Path,
        parent: Path,
        *,
        backend: str,
        profile: str,
        runner_id: str | None,
    ):
        runner = runners_by_id(root).get(runner_id) if runner_id else None
        destination = resolve_destination(
            parent,
            capsule_id=CAPSULE_ID,
            profile_id=profile,
            backend_id=backend,  # type: ignore[arg-type]
            runner=runner,
        )
        return validate_request(
            MaterializationRequest(
                collection_root=root,
                capsule_path=capsule,
                capsule_id=CAPSULE_ID,
                profile_id=profile,
                backend_id=backend,  # type: ignore[arg-type]
                runner=runner,
                destination=destination,
            )
        )

    def test_base_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, capsule = create_collection(base / "vault")
            parent = base / "dest"
            parent.mkdir()
            validated = self._validated(
                root,
                capsule,
                parent,
                backend="base",
                profile="linux-base-only",
                runner_id=None,
            )
            command = build_command(
                validated,
                bwrap=Path("/usr/bin/bwrap"),
                ogv=Path("/usr/bin/ogv"),
            )
            self.assertIn("materialize", command)
            self.assertNotIn("materialize-playable", command)
            self.assertIn("--unshare-net", command)

    def test_direct_wine_command_accepts_overlay_capsule(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, capsule = create_collection(base / "vault")
            parent = base / "dest"
            parent.mkdir()
            validated = self._validated(
                root,
                capsule,
                parent,
                backend="direct-wine",
                profile=PROFILE_ID,
                runner_id=SODA_RUNNER_ID,
            )
            overlay = base / "overlay/capsule.json"
            bridge = Path("/usr/bin/ogv-state-capsule-bridge")
            command = build_command(
                validated,
                bwrap=Path("/usr/bin/bwrap"),
                ogv=Path("/usr/bin/ogv"),
                capsule_path=overlay,
                state_bridge=bridge,
            )
            self.assertIn("materialize-playable", command)
            self.assertIn(str(bridge), command)
            self.assertEqual(command[command.index("--capsule") + 1], str(overlay))
            self.assertEqual(
                command[command.index("--state-capsule") + 1],
                str(capsule),
            )
            self.assertIn("--state-backup", command)
            self.assertIn("--unshare-net", command)



    def test_overlay_with_state_rejects_missing_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, capsule = create_collection(base / "vault")
            parent = base / "dest"
            parent.mkdir()
            validated = self._validated(
                root,
                capsule,
                parent,
                backend="direct-wine",
                profile=PROFILE_ID,
                runner_id=SODA_RUNNER_ID,
            )
            overlay = base / "overlay/capsule.json"
            with self.assertRaisesRegex(
                Exception,
                "requires the original-capsule bridge",
            ):
                build_command(
                    validated,
                    bwrap=Path("/usr/bin/bwrap"),
                    ogv=Path("/usr/bin/ogv"),
                    capsule_path=overlay,
                )


    def test_bottles_restore_state_is_network_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, capsule = create_collection(base / "vault")
            parent = base / "dest"
            parent.mkdir()
            runner = runners_by_id(root)[SODA_RUNNER_ID]
            bottles_path = base / "bottles"
            bottles_path.mkdir()
            from helpers import BOTTLES_PROFILE_ID, bottles_backend
            request = validate_request(
                MaterializationRequest(
                    collection_root=root,
                    capsule_path=capsule,
                    capsule_id=CAPSULE_ID,
                    profile_id=BOTTLES_PROFILE_ID,
                    backend_id="bottles",
                    runner=runner,
                    destination=resolve_destination(
                        parent,
                        capsule_id=CAPSULE_ID,
                        profile_id=BOTTLES_PROFILE_ID,
                        backend_id="bottles",
                        runner=runner,
                    ),
                    bottles_path=bottles_path,
                    bottles_backend=bottles_backend(root),
                )
            )
            command = build_restore_state_command(
                request,
                state_root=request.destination / "objects/baseline/Game",
                backup=request.state_backup,
                snapshot=parent / ".snapshot",
                bwrap=Path("/usr/bin/bwrap"),
                ogv=Path("/usr/bin/ogv"),
            )
            self.assertIn("restore-state", command)
            self.assertIn("--confirm-stopped", command)
            self.assertIn("--unshare-net", command)
            self.assertEqual(
                command[command.index("--capsule") + 1],
                str(capsule),
            )

    def test_execution_commands_are_direct_core_calls(self) -> None:
        destination = Path("/tmp/materialized")
        verify = build_verify_playable_command(
            destination,
            ogv=Path("/usr/bin/ogv"),
        )
        run = build_run_playable_command(
            destination,
            ogv=Path("/usr/bin/ogv"),
        )
        self.assertEqual(
            verify,
            [
                "/usr/bin/ogv",
                "verify-playable",
                "--destination",
                str(destination),
                "--json",
            ],
        )
        self.assertEqual(
            run,
            [
                "/usr/bin/ogv",
                "run-playable",
                "--destination",
                str(destination),
                "--json",
            ],
        )


if __name__ == "__main__":
    unittest.main()
