from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from offline_game_vault_gui.core import (
    CoreResolutionError,
    inspect_core,
    resolve_ogv_command,
    resolve_ogv_executable,
)


REQUIRED = (
    "discover-bottles-path",
    "list-preserved-runners",
    "list-shared-umu-runtimes",
    "materialize-experimental",
    "verify-playable",
    "run-playable",
    "remove-playable",
    "verify-umu",
    "run-umu",
    "remove-umu",
    "verify-bottles-deployment",
    "run-bottles",
    "remove-bottles-deployment",
)


def write_fake_core(
    path: Path,
    *,
    commands: tuple[str, ...] = REQUIRED,
) -> None:
    help_text = " ".join(commands)
    path.write_text(
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = \"--version\" ]; then\n"
        "  printf '%s\\n' 'ogv 0.11.3'\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"${1:-}\" = \"--help\" ]; then\n"
        f"  printf '%s\\n' {help_text!r}\n"
        "  exit 0\n"
        "fi\n"
        "exit 2\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


class CoreResolutionTests(unittest.TestCase):
    def test_explicit_executable_has_priority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "ogv"
            write_fake_core(executable)
            with patch.dict(
                os.environ,
                {"OGV_EXECUTABLE": str(executable)},
                clear=False,
            ):
                os.environ.pop("OGV_SOURCE_ROOT", None)
                self.assertEqual(
                    resolve_ogv_executable(),
                    executable.resolve(),
                )
                command, environment = resolve_ogv_command()
                self.assertEqual(
                    command,
                    [str(executable.resolve())],
                )
                self.assertEqual(
                    environment["PYTHONDONTWRITEBYTECODE"],
                    "1",
                )

    def test_source_checkout_is_used_when_explicitly_configured(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "offline-game-vault"
            (source / "src/offline_game_vault").mkdir(parents=True)
            (source / "pyproject.toml").write_text(
                "[project]\nname='offline-game-vault'\n",
                encoding="utf-8",
            )
            (source / "src/offline_game_vault/cli.py").write_text(
                "\n",
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {"OGV_SOURCE_ROOT": str(source)},
                clear=False,
            ):
                os.environ.pop("OGV_EXECUTABLE", None)
                command, environment = resolve_ogv_command()
            self.assertGreater(len(command), 1)
            self.assertIn(
                str(source.resolve() / "src"),
                environment["PYTHONPATH"],
            )

    def test_capability_probe_accepts_core_0113(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "ogv"
            write_fake_core(executable)
            with patch.dict(
                os.environ,
                {"OGV_EXECUTABLE": str(executable)},
                clear=False,
            ):
                os.environ.pop("OGV_SOURCE_ROOT", None)
                info = inspect_core()
        self.assertEqual(info.version, "0.11.3")
        self.assertIn("materialize-experimental", info.commands)
        self.assertIn("list-shared-umu-runtimes", info.commands)

    def test_capability_probe_rejects_old_core_before_materialization(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "ogv"
            write_fake_core(
                executable,
                commands=tuple(
                    command
                    for command in REQUIRED
                    if command != "list-shared-umu-runtimes"
                ),
            )
            with patch.dict(
                os.environ,
                {"OGV_EXECUTABLE": str(executable)},
                clear=False,
            ):
                os.environ.pop("OGV_SOURCE_ROOT", None)
                with self.assertRaisesRegex(
                    CoreResolutionError,
                    "list-shared-umu-runtimes",
                ):
                    inspect_core()


if __name__ == "__main__":
    unittest.main()
