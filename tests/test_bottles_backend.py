from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from offline_game_vault_gui.bottles_backend import (
    BottlesEnvironment,
    BottlesEnvironmentError,
    recover_interrupted_runner_override,
    scan_bottles_environment,
    temporary_runner_override,
)

from helpers import create_base_destination


class BottlesBackendTests(unittest.TestCase):
    def test_scans_managed_path_and_exact_runners(self) -> None:
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            flatpak = base / "flatpak"
            flatpak.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            flatpak.chmod(0o755)
            bottles = base / "bottles"
            bottles.mkdir()

            with (
                patch(
                    "offline_game_vault_gui.bottles_backend._resolve_flatpak",
                    return_value=flatpak,
                ),
                patch(
                    "offline_game_vault_gui.bottles_backend._flatpak_identity",
                    return_value=(
                        "app/com.usebottles.bottles/x86_64/stable",
                        "b" * 64,
                    ),
                ),
                patch(
                    "offline_game_vault_gui.bottles_backend._run_json",
                    side_effect=[
                        {"path": str(bottles)},
                        {"runners": ["ge-proton11-1", "soda-9.0-1"]},
                    ],
                ),
            ):
                result = scan_bottles_environment()

            self.assertEqual(result.bottles_path, bottles)
            self.assertEqual(
                result.application_ref,
                "app/com.usebottles.bottles/x86_64/stable",
            )
            self.assertEqual(result.application_commit, "b" * 64)
            self.assertEqual(
                result.installed_runners,
                frozenset({"ge-proton11-1", "soda-9.0-1"}),
            )

    def test_decodes_top_level_json_string_with_noise(self) -> None:
        from offline_game_vault_gui.bottles_backend import _decode_json_output

        value = _decode_json_output(
            'initialization message\n"/tmp/bottles"\n',
            "bottles-path",
        )
        self.assertEqual(value, "/tmp/bottles")

    def test_uses_filesystem_runners_when_components_cli_fails(self) -> None:
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            flatpak = base / "flatpak"
            flatpak.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            flatpak.chmod(0o755)
            managed = base / "data" / "bottles"
            managed.mkdir(parents=True)
            runners = managed.parent / "runners"
            (runners / "ge-proton11-1").mkdir(parents=True)

            with (
                patch(
                    "offline_game_vault_gui.bottles_backend._resolve_flatpak",
                    return_value=flatpak,
                ),
                patch(
                    "offline_game_vault_gui.bottles_backend._flatpak_identity",
                    return_value=(
                        "app/com.usebottles.bottles/x86_64/stable",
                        "b" * 64,
                    ),
                ),
                patch(
                    "offline_game_vault_gui.bottles_backend._run_json",
                    side_effect=[
                        str(managed),
                        BottlesEnvironmentError("components unavailable"),
                    ],
                ),
            ):
                result = scan_bottles_environment()

            self.assertEqual(
                result.installed_runners,
                frozenset({"ge-proton11-1"}),
            )
            self.assertEqual(len(result.warnings), 1)

    def test_rejects_empty_runner_inventory(self) -> None:
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            flatpak = base / "flatpak"
            flatpak.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            flatpak.chmod(0o755)
            bottles = base / "bottles"
            bottles.mkdir()

            with (
                patch(
                    "offline_game_vault_gui.bottles_backend._resolve_flatpak",
                    return_value=flatpak,
                ),
                patch(
                    "offline_game_vault_gui.bottles_backend._flatpak_identity",
                    return_value=(
                        "app/com.usebottles.bottles/x86_64/stable",
                        "b" * 64,
                    ),
                ),
                patch(
                    "offline_game_vault_gui.bottles_backend._run_json",
                    side_effect=[{"path": str(bottles)}, {"runners": []}],
                ),
            ):
                with self.assertRaises(BottlesEnvironmentError):
                    scan_bottles_environment()

    def test_temporary_override_restores_source_and_leaves_evidence_in_copy(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary:
            materialization = Path(temporary) / "materialized"
            bottle = create_base_destination(materialization)
            bottle_yml = bottle / "bottle.yml"
            original = bottle_yml.read_bytes()
            original_mode = bottle_yml.stat().st_mode & 0o777
            digest = "sha256:" + hashlib.sha256(b"runner").hexdigest()

            with temporary_runner_override(
                materialization,
                selected_runner="soda-9.0-1",
                runner_digest=digest,
                gui_version="0.1.08",
            ) as (active, original_runner, changed):
                self.assertTrue(changed)
                self.assertEqual(original_runner, "ge-proton11-1")
                self.assertIn(
                    'Runner: "soda-9.0-1"',
                    active.read_text(encoding="utf-8"),
                )
                evidence = active.parent / ".ogv-gui-runner-selection.json"
                document = json.loads(evidence.read_text(encoding="utf-8"))
                self.assertFalse(document["acceptance_transferred"])
                self.assertEqual(document["selected_runner"], "soda-9.0-1")

            self.assertEqual(bottle_yml.read_bytes(), original)
            self.assertEqual(bottle_yml.stat().st_mode & 0o777, original_mode)
            self.assertFalse(
                (materialization / ".ogv-gui-bottle-yml.backup").exists()
            )
            self.assertFalse(
                (materialization / ".ogv-gui-bottles-runner-override.json").exists()
            )
            self.assertFalse(
                (bottle / ".ogv-gui-runner-selection.json").exists()
            )

    def test_recovers_interrupted_override(self) -> None:
        with TemporaryDirectory() as temporary:
            materialization = Path(temporary) / "materialized"
            bottle = create_base_destination(materialization)
            bottle_yml = bottle / "bottle.yml"
            original = bottle_yml.read_bytes()
            backup = materialization / ".ogv-gui-bottle-yml.backup"
            journal = (
                materialization / ".ogv-gui-bottles-runner-override.json"
            )
            backup.write_bytes(original)
            relative = bottle_yml.relative_to(materialization).as_posix()
            journal.write_text(
                json.dumps(
                    {
                        "schema": 0,
                        "operation": "temporary-bottles-runner-override",
                        "bottle_yml": relative,
                        "original_sha256": hashlib.sha256(original).hexdigest(),
                        "original_runner": "ge-proton11-1",
                        "selected_runner": "soda-9.0-1",
                    }
                ),
                encoding="utf-8",
            )
            bottle_yml.write_text(
                'Name: "Game"\nPath: "Game"\nCustom_Path: false\n'
                'Runner: "soda-9.0-1"\n',
                encoding="utf-8",
            )

            self.assertTrue(
                recover_interrupted_runner_override(materialization)
            )
            self.assertEqual(bottle_yml.read_bytes(), original)
            self.assertFalse(backup.exists())
            self.assertFalse(journal.exists())


if __name__ == "__main__":
    unittest.main()
