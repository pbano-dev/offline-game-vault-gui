from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from offline_game_vault_gui.experimental_service import (
    ExperimentalServiceError,
    list_preserved_runners,
    materialize_experimental,
    remove_experimental,
    run_experimental,
    verify_experimental,
)
from offline_game_vault_gui.model import (
    ExperimentalRequest,
    RunnerRecord,
)


def make_runner(
    runner_id: str = "ge-proton11-1",
    backends: tuple[str, ...] = (
        "bottles",
        "direct-wine",
        "umu",
    ),
) -> RunnerRecord:
    return RunnerRecord(
        runner_id=runner_id,
        digest="a" * 64,
        archive_path="objects/sha256/aa/aa/" + "a" * 64,
        size=123,
        format="tar.gz",
        source_root="GE-Proton",
        wine_path="files/bin/wine",
        wineserver_path="files/bin/wineserver",
        compatible_backends=backends,
        metadata_source="test",
        proton_path="proton",
        kind="proton",
    )


class ExperimentalServiceTests(unittest.TestCase):
    def _request(
        self,
        root: Path,
        backend: str,
    ) -> ExperimentalRequest:
        capsule = root / "capsule.json"
        capsule.write_text("{}\n", encoding="utf-8")
        output = root / "output"
        output.mkdir()
        bottles = root / "bottles"
        bottles.mkdir()
        return ExperimentalRequest(
            collection_root=root,
            capsule_path=capsule,
            capsule_id="game",
            backend_id=backend,  # type: ignore[arg-type]
            runner=make_runner(),
            destination=(
                output / "variant"
                if backend != "bottles"
                else None
            ),
            source_profile_id=None,
            bottles_path=bottles if backend == "bottles" else None,
            bottle_name="variant" if backend == "bottles" else None,
        )

    def test_direct_wine_uses_experimental_core_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            request = self._request(Path(temporary), "direct-wine")
            captured: list[str] = []

            def fake_run(arguments, *, cwd=None):
                captured.extend(arguments)
                return (
                    subprocess.CompletedProcess(
                        arguments, 0, stdout="{}", stderr=""
                    ),
                    {
                        "materialized": True,
                        "backend": "direct-wine",
                        "profile_id": "experimental-direct-wine",
                        "runner_id": request.runner.runner_id,
                    },
                )

            script_calls: list[tuple[str, tuple[str, ...]]] = []

            def fake_script(target, script_name, arguments=(), *, cwd=None):
                script_calls.append((script_name, tuple(arguments)))
                return (
                    subprocess.CompletedProcess(
                        [script_name], 0, stdout="{}", stderr=""
                    ),
                    {
                        "backend": "direct-wine",
                        "complete": True,
                    },
                )

            with (
                patch(
                    "offline_game_vault_gui.experimental_service._run_json",
                    side_effect=fake_run,
                ),
                patch(
                    "offline_game_vault_gui.experimental_service._run_script_json",
                    side_effect=fake_script,
                ),
            ):
                outcome = materialize_experimental(
                    request,
                    play=True,
                )

            self.assertEqual(captured[0], "materialize-experimental")
            self.assertIn("--backend", captured)
            self.assertIn("direct-wine", captured)
            self.assertNotIn("--play", captured)
            self.assertNotIn("--source-profile", captured)
            self.assertEqual(script_calls, [("JUGAR.sh", ("--json",))])
            self.assertEqual(outcome.backend_id, "direct-wine")

    def test_bottles_passes_managed_path_and_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            request = self._request(Path(temporary), "bottles")
            captured: list[str] = []

            def fake_run(arguments, *, cwd=None):
                captured.extend(arguments)
                return (
                    subprocess.CompletedProcess(
                        arguments, 0, stdout="{}", stderr=""
                    ),
                    {
                        "materialized": True,
                        "backend": "bottles",
                        "profile_id": "experimental-bottles",
                        "runner_id": request.runner.runner_id,
                    },
                )

            with patch(
                "offline_game_vault_gui.experimental_service._run_json",
                side_effect=fake_run,
            ):
                materialize_experimental(request, play=False)

            self.assertIn("--bottles-path", captured)
            self.assertIn("--bottle-name", captured)
            self.assertNotIn("--destination", captured)

    def test_umu_delegates_shared_runtime_resolution_to_core(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            request = self._request(Path(temporary), "umu")
            captured: list[str] = []

            def fake_run(arguments, *, cwd=None):
                captured.extend(arguments)
                return (
                    subprocess.CompletedProcess(
                        arguments, 0, stdout="{}", stderr=""
                    ),
                    {
                        "materialized": True,
                        "backend": "umu",
                        "profile_id": "experimental-umu",
                        "runner_id": request.runner.runner_id,
                        "backend_result": {
                            "shared_runtime_id": "umu-runtime-test"
                        },
                    },
                )

            with patch(
                "offline_game_vault_gui.experimental_service._run_json",
                side_effect=fake_run,
            ):
                materialize_experimental(request, play=False)

            self.assertIn("--backend", captured)
            self.assertIn("umu", captured)
            self.assertNotIn("--umu-backend", captured)

    def test_operations_use_materialization_scripts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            request = self._request(Path(temporary), "umu")
            assert request.destination is not None
            request.destination.mkdir()
            for name in ("JUGAR.sh", "VERIFICAR.sh", "DESINSTALAR.sh"):
                script = request.destination / name
                script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                script.chmod(0o700)

            calls: list[tuple[str, tuple[str, ...], Path | None]] = []

            def fake_script(target, script_name, arguments=(), *, cwd=None):
                calls.append((script_name, tuple(arguments), cwd))
                return (
                    subprocess.CompletedProcess(
                        [script_name], 0, stdout="{}", stderr=""
                    ),
                    {
                        "backend": "umu",
                        "complete": True,
                        "removed": script_name == "DESINSTALAR.sh",
                    },
                )

            with patch(
                "offline_game_vault_gui.experimental_service._run_script_json",
                side_effect=fake_script,
            ):
                verify_experimental(request)
                run_experimental(request)
                remove_experimental(request)

            self.assertEqual(
                [item[0] for item in calls],
                ["VERIFICAR.sh", "JUGAR.sh", "DESINSTALAR.sh"],
            )
            self.assertEqual(calls[0][1], ("--json",))
            self.assertEqual(calls[1][1], ("--json",))
            self.assertEqual(
                calls[2][1],
                ("--confirm-state-preserved", "--json"),
            )
            self.assertEqual(calls[2][2], request.destination.parent)

    def test_runner_catalog_comes_from_core_and_keeps_proton_for_all_backends(
        self,
    ) -> None:
        payload = {
            "schema": 0,
            "warnings": [],
            "runners": [
                {
                    "runner_id": "proton",
                    "digest": "sha256:" + "b" * 64,
                    "archive_path": "objects/sha256/bb/bb/" + "b" * 64,
                    "size": 9,
                    "format": "tar.gz",
                    "source_root": "Proton",
                    "wine_path": "files/bin/wine",
                    "wineserver_path": "files/bin/wineserver",
                    "compatible_backends": [
                        "direct-wine",
                        "bottles",
                        "umu",
                    ],
                    "metadata_source": "receipt",
                    "proton_path": "proton",
                    "kind": "proton",
                    "acceptance_status": "not_tested",
                }
            ],
        }
        with patch(
            "offline_game_vault_gui.experimental_service._run_json",
            return_value=(
                subprocess.CompletedProcess([], 0, "", ""),
                payload,
            ),
        ):
            runners, warnings = list_preserved_runners(Path("vault"))
        self.assertEqual(warnings, ())
        self.assertEqual(
            runners[0].compatible_backends,
            ("direct-wine", "bottles", "umu"),
        )



if __name__ == "__main__":
    unittest.main()
