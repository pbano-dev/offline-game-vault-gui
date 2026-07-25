from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

from offline_game_vault_gui.bottles_control import (
    refresh_bottles_control,
    validate_bottles_control,
    write_bottles_control,
)
from offline_game_vault_gui.guard import (
    bottle_deployment_name,
    resolve_destination,
    validate_request,
)
from offline_game_vault_gui.model import MaterializationRequest

from helpers import (
    BOTTLES_APP_COMMIT,
    BOTTLES_APP_REF,
    BOTTLES_PROFILE_ID,
    CAPSULE_ID,
    SODA_RUNNER_ID,
    bottles_backend,
    create_bottles_deployment,
    create_collection,
    runners_by_id,
)


class BottlesControlTests(unittest.TestCase):
    def test_control_is_lightweight_and_launcher_runs_bottles_cli_directly(self) -> None:
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, capsule = create_collection(base / "vault")
            runner = runners_by_id(root)[SODA_RUNNER_ID]
            backend = bottles_backend(root)
            destination = base / "control"
            bottles_path = base / "bottles"
            bottles_path.mkdir()
            deployment = create_bottles_deployment(
                bottles_path,
                bottle_name="ogv-test",
                runner_id=SODA_RUNNER_ID,
            )
            receipt, launcher, uninstaller = write_bottles_control(
                destination,
                capsule_path=capsule,
                capsule_id=CAPSULE_ID,
                profile_id=BOTTLES_PROFILE_ID,
                runner=runner,
                bottle_name="ogv-test",
                backend=backend,
            )

            self.assertTrue(receipt.is_file())
            self.assertTrue(os.access(launcher, os.X_OK))
            self.assertTrue(os.access(uninstaller, os.X_OK))
            self.assertEqual(
                {path.name for path in destination.iterdir()},
                {receipt.name, launcher.name, uninstaller.name},
            )

            text = launcher.read_text(encoding="utf-8")
            self.assertIn("bottles-cli", text)
            self.assertNotIn("run-bottles", text)
            self.assertNotIn("command -v ogv", text)
            self.assertNotIn(str(bottles_path), text)

            fake_flatpak = base / "flatpak"
            fake_flatpak.write_text(
                "#!/usr/bin/env bash\n"
                "set -e\n"
                "if [[ \"$1\" == info && \"$2\" == --show-ref ]]; then\n"
                f"  echo '{BOTTLES_APP_REF}'\n"
                "elif [[ \"$1\" == info && \"$2\" == --show-commit ]]; then\n"
                f"  echo '{BOTTLES_APP_COMMIT}'\n"
                "elif [[ \"$1\" == run && \"${4:-}\" == --json ]]; then\n"
                f"  echo '{bottles_path}'\n"
                "else\n"
                "  printf '%s\\n' \"$@\"\n"
                "fi\n",
                encoding="utf-8",
            )
            fake_flatpak.chmod(0o755)

            result = subprocess.run(
                [str(launcher)],
                env={
                    **os.environ,
                    "FLATPAK_EXECUTABLE": str(fake_flatpak),
                    "PYTHON_EXECUTABLE": "/usr/bin/python3",
                },
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout.splitlines(),
                [
                    "run",
                    "--unshare=network",
                    "--command=bottles-cli",
                    "com.usebottles.bottles",
                    "run",
                    "-b",
                    "ogv-test",
                    "-e",
                    str(deployment / "drive_c/Games/Test/game.exe"),
                ],
            )


    def test_refresh_upgrades_existing_lightweight_control(self) -> None:
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, capsule = create_collection(base / "vault")
            runner = runners_by_id(root)[SODA_RUNNER_ID]
            backend = bottles_backend(root)
            destination = base / "control"
            receipt, launcher, _ = write_bottles_control(
                destination,
                capsule_path=capsule,
                capsule_id=CAPSULE_ID,
                profile_id=BOTTLES_PROFILE_ID,
                runner=runner,
                bottle_name="ogv-test",
                backend=backend,
            )

            legacy_text = (
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "ogv run-bottles \"$@\"\n"
            )
            launcher.write_text(legacy_text, encoding="utf-8")
            launcher.chmod(0o755)

            document = json.loads(receipt.read_text(encoding="utf-8"))
            document.pop("launcher_protocol", None)
            document["bottles_path_resolution"] = (
                "bottles-cli-info-bottles-path"
            )
            document["launcher_sha256"] = hashlib.sha256(
                launcher.read_bytes()
            ).hexdigest()
            receipt.write_text(
                json.dumps(
                    document,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ) + "\n",
                encoding="utf-8",
            )

            self.assertIsNotNone(
                validate_bottles_control(
                    destination,
                    capsule_id=CAPSULE_ID,
                    profile_id=BOTTLES_PROFILE_ID,
                    runner=runner,
                    bottle_name="ogv-test",
                    backend=backend,
                )
            )

            refreshed_receipt, refreshed_launcher, _ = (
                refresh_bottles_control(
                    destination,
                    capsule_path=capsule,
                    capsule_id=CAPSULE_ID,
                    profile_id=BOTTLES_PROFILE_ID,
                    runner=runner,
                    bottle_name="ogv-test",
                    backend=backend,
                )
            )

            refreshed = json.loads(
                refreshed_receipt.read_text(encoding="utf-8")
            )
            self.assertEqual(
                refreshed["launcher_protocol"],
                "direct-bottles-cli-v1",
            )
            self.assertEqual(
                refreshed["bottles_path_resolution"],
                "bottles-cli-json-or-plain",
            )
            launcher_text = refreshed_launcher.read_text(encoding="utf-8")
            self.assertIn("--command=bottles-cli", launcher_text)
            self.assertNotIn("ogv run-bottles", launcher_text)


    def test_guard_recognizes_single_copy_control(self) -> None:
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, capsule = create_collection(base / "vault")
            parent = base / "materialized"
            parent.mkdir()
            bottles_path = base / "bottles"
            bottles_path.mkdir()
            runner = runners_by_id(root)[SODA_RUNNER_ID]
            backend = bottles_backend(root)
            destination = resolve_destination(
                parent,
                capsule_id=CAPSULE_ID,
                profile_id=BOTTLES_PROFILE_ID,
                backend_id="bottles",
                runner=runner,
            )
            bottle_name = bottle_deployment_name(
                CAPSULE_ID,
                BOTTLES_PROFILE_ID,
                SODA_RUNNER_ID,
            )
            create_bottles_deployment(
                bottles_path,
                bottle_name=bottle_name,
                runner_id=SODA_RUNNER_ID,
            )
            write_bottles_control(
                destination,
                capsule_path=capsule,
                capsule_id=CAPSULE_ID,
                profile_id=BOTTLES_PROFILE_ID,
                runner=runner,
                bottle_name=bottle_name,
                backend=backend,
            )
            request = MaterializationRequest(
                collection_root=root,
                capsule_path=capsule,
                capsule_id=CAPSULE_ID,
                profile_id=BOTTLES_PROFILE_ID,
                backend_id="bottles",
                runner=runner,
                destination=destination,
                bottles_path=bottles_path,
                bottles_backend=backend,
            )
            validated = validate_request(request)
            self.assertTrue(validated.reusable)
            self.assertTrue(validated.control_reusable)
            self.assertFalse(validated.source_reusable)
            self.assertIsNotNone(
                validate_bottles_control(
                    destination,
                    capsule_id=CAPSULE_ID,
                    profile_id=BOTTLES_PROFILE_ID,
                    runner=runner,
                    bottle_name=bottle_name,
                    backend=backend,
                )
            )


if __name__ == "__main__":
    unittest.main()
