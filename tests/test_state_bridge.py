from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


CAPSULE_ID = "steam-1-test-1.0"
PROFILE_ID = "linux-direct-wine"


class StateCapsuleBridgeTests(unittest.TestCase):
    def _write_json(self, path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _fake_core(self, root: Path) -> Path:
        package = root / "src/offline_game_vault"
        package.mkdir(parents=True)
        (root / "pyproject.toml").write_text(
            "[project]\nname='offline-game-vault-test'\n",
            encoding="utf-8",
        )
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "playable.py").write_text(
            """
from pathlib import Path


class Result:
    def __init__(self, payload):
        self.payload = payload

    def to_dict(self):
        return self.payload


class Verification:
    verified = True


class Restore:
    restored_count = 1


observed_verify_capsule = None
observed_restore_capsule = None


def verify_state_backup(*, capsule_path, backup):
    global observed_verify_capsule
    observed_verify_capsule = Path(capsule_path).name
    if observed_verify_capsule != "original-capsule.json":
        raise RuntimeError("State backup failed verification.")
    return Verification()


def restore_state(
    *,
    capsule_path,
    state_root,
    backup,
    snapshot,
    confirm_stopped,
):
    global observed_restore_capsule
    observed_restore_capsule = Path(capsule_path).name
    if observed_restore_capsule != "original-capsule.json":
        raise RuntimeError("State backup failed verification.")
    return Restore()


def materialize_playable_profile(
    *,
    capsule_path,
    profile_id,
    vault_root,
    destination,
    state_backup,
):
    verification = verify_state_backup(
        capsule_path=capsule_path,
        backup=state_backup,
    )
    restore = restore_state(
        capsule_path=capsule_path,
        state_root=Path(destination) / "prefix",
        backup=state_backup,
        snapshot=Path(destination).parent / "snapshot",
        confirm_stopped=True,
    )
    return Result(
        {
            "complete": verification.verified,
            "restored_count": restore.restored_count,
            "capsule_seen_by_materializer": Path(capsule_path).name,
            "capsule_seen_by_verify_state": observed_verify_capsule,
            "capsule_seen_by_restore_state": observed_restore_capsule,
            "profile_id": profile_id,
        }
    )
""".lstrip(),
            encoding="utf-8",
        )
        return root

    def _run(
        self,
        base: Path,
        *,
        original_state: list[dict[str, object]],
        derived_state: list[dict[str, object]],
        derived_capsule_id: str = CAPSULE_ID,
    ) -> subprocess.CompletedProcess[str]:
        core = self._fake_core(base / "core")
        vault = base / "vault"
        vault.mkdir()
        backup = base / "accepted"
        backup.mkdir()
        destination = base / "destination"

        original = base / "original-capsule.json"
        derived = base / "derived-capsule.json"
        self._write_json(
            original,
            {
                "schema": 0,
                "capsule_id": CAPSULE_ID,
                "persistent_state": original_state,
            },
        )
        self._write_json(
            derived,
            {
                "schema": 0,
                "capsule_id": derived_capsule_id,
                "persistent_state": derived_state,
                "profiles": [{"id": PROFILE_ID, "status": "not_tested"}],
            },
        )

        bridge = (
            Path(__file__).resolve().parents[1]
            / "scripts/ogv-state-capsule-bridge.py"
        )
        environment = os.environ.copy()
        environment["OGV_SOURCE_ROOT"] = str(core)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"

        return subprocess.run(
            [
                str(bridge),
                "materialize-playable",
                "--capsule",
                str(derived),
                "--state-capsule",
                str(original),
                "--profile",
                PROFILE_ID,
                "--vault-root",
                str(vault),
                "--destination",
                str(destination),
                "--state-backup",
                str(backup),
                "--json",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            check=False,
        )

    def test_bridge_is_directly_executable_with_python_shebang(self) -> None:
        bridge = (
            Path(__file__).resolve().parents[1]
            / "scripts/ogv-state-capsule-bridge.py"
        )
        self.assertTrue(os.access(bridge, os.X_OK))
        self.assertTrue(
            bridge.read_bytes().startswith(b"#!/usr/bin/env python3\n")
        )

    def test_uses_original_capsule_only_for_state_calls(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = self._run(
                Path(temporary),
                original_state=[
                    {"id": "save", "path": "drive_c/save.dat", "backup": True}
                ],
                derived_state=[
                    {"id": "save", "path": "drive_c/save.dat", "backup": True}
                ],
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["materialization"]["complete"])
            self.assertEqual(
                payload["materialization"]["capsule_seen_by_materializer"],
                "derived-capsule.json",
            )
            self.assertEqual(
                payload["materialization"]["restored_count"],
                1,
            )
            self.assertEqual(
                payload["materialization"]["capsule_seen_by_verify_state"],
                "original-capsule.json",
            )
            self.assertEqual(
                payload["materialization"]["capsule_seen_by_restore_state"],
                "original-capsule.json",
            )

    def test_rejects_changed_persistent_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = self._run(
                Path(temporary),
                original_state=[
                    {"id": "save", "path": "drive_c/save.dat", "backup": True}
                ],
                derived_state=[
                    {"id": "other", "path": "drive_c/other.dat", "backup": True}
                ],
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn(
                "overlay changed persistent_state",
                result.stderr,
            )

    def test_rejects_different_capsule_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = self._run(
                Path(temporary),
                original_state=[],
                derived_state=[],
                derived_capsule_id="steam-2-other-1.0",
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn(
                "same capsule_id",
                result.stderr,
            )


if __name__ == "__main__":
    unittest.main()
