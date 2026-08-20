from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
from typing import Any, Mapping, Sequence

from .model import (
    ComponentSet,
    CompositionRequest,
    CompositionResult,
    RunnerRecord,
    StateBackupRecord,
)


MINIMUM_CORE = (0, 19, 0)
REQUIRED_COMMANDS = (
    "discover-bottles-path",
    "list-preserved-runners",
    "list-shared-umu-runtimes",
    "verify-state-backup",
    "compose",
)


class CoreError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CoreProbe:
    version: str
    version_tuple: tuple[int, int, int]
    description: str


@dataclass(frozen=True, slots=True)
class CoreClient:
    """Strict subprocess/JSON client for the public Offline Game Vault CLI."""

    command: tuple[str, ...]
    environment: Mapping[str, str]
    description: str

    @classmethod
    def resolve(
        cls,
        *,
        executable: str | None = None,
        source_root: Path | None = None,
        repository_root: Path | None = None,
    ) -> "CoreClient":
        explicit_executable = executable or os.environ.get("OGV_EXECUTABLE")
        if explicit_executable:
            path = Path(explicit_executable).expanduser()
            if (
                path.is_symlink()
                or not path.is_file()
                or not os.access(path, os.X_OK)
            ):
                raise CoreError(
                    "OGV_EXECUTABLE is not a regular executable file"
                )
            resolved = path.resolve()
            return cls(
                command=(str(resolved),),
                environment=dict(os.environ),
                description=f"executable:{resolved}",
            )

        explicit_source = source_root
        if explicit_source is None:
            raw_source = os.environ.get("OGV_SOURCE_ROOT")
            if raw_source:
                explicit_source = Path(raw_source)
        if explicit_source is not None:
            return cls._from_source_root(explicit_source, explicit=True)

        # ``base`` is this repository's own root, so the core checkout is
        # looked for beside it. Using the parent directory here searched one
        # level too high and silently fell through to an installed ``ogv``.
        base = (
            repository_root.expanduser().resolve()
            if repository_root is not None
            else Path(__file__).resolve().parents[2]
        )
        sibling = base.parent / "offline-game-vault"
        try:
            return cls._from_source_root(sibling, explicit=False)
        except CoreError:
            pass

        installed = shutil.which("ogv")
        if installed:
            return cls(
                command=(installed,),
                environment=dict(os.environ),
                description=f"path:{installed}",
            )

        raise CoreError(
            "No compatible core was found. Select an offline-game-vault "
            "source checkout or set OGV_EXECUTABLE/OGV_SOURCE_ROOT."
        )

    @classmethod
    def _from_source_root(
        cls,
        source_root: Path,
        *,
        explicit: bool,
    ) -> "CoreClient":
        source_root = source_root.expanduser().resolve()
        cli = source_root / "src/offline_game_vault/cli.py"
        if cli.is_symlink() or not cli.is_file():
            label = (
                "OGV_SOURCE_ROOT"
                if explicit
                else "Sibling core checkout"
            )
            raise CoreError(f"{label} does not contain the core CLI")

        environment = dict(os.environ)
        pythonpath = str(source_root / "src")
        current = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            pythonpath + os.pathsep + current if current else pythonpath
        )
        environment["PYTHONDONTWRITEBYTECODE"] = "1"

        return cls(
            command=(sys.executable, "-m", "offline_game_vault.cli"),
            environment=environment,
            description=f"source:{source_root}",
        )

    def probe(self) -> CoreProbe:
        process = self._run(("--version",), timeout=20)
        if process.returncode != 0:
            detail = (process.stderr or process.stdout).strip()
            raise CoreError(
                f"Core version probe failed ({process.returncode}): {detail}"
            )

        text = (process.stdout or process.stderr).strip()
        match = re.search(r"\b(\d+)\.(\d+)\.(\d+)\b", text)
        if match is None:
            raise CoreError(f"Could not parse core version from: {text!r}")

        version_tuple = tuple(int(item) for item in match.groups())
        if version_tuple < MINIMUM_CORE:
            minimum = ".".join(str(item) for item in MINIMUM_CORE)
            raise CoreError(
                f"Core {'.'.join(match.groups())} is too old; "
                f"{minimum} or newer is required"
            )

        for command in REQUIRED_COMMANDS:
            result = self._run((command, "--help"), timeout=20)
            if result.returncode != 0:
                raise CoreError(f"Core command is unavailable: {command}")

        return CoreProbe(
            version=".".join(match.groups()),
            version_tuple=version_tuple,
            description=self.description,
        )

    def run_json(
        self,
        arguments: Sequence[str],
        *,
        timeout: int = 120,
    ) -> dict[str, Any]:
        process = self._run(tuple(arguments), timeout=timeout)
        if process.returncode != 0:
            detail = (process.stderr or process.stdout).strip()
            if len(detail) > 4000:
                detail = detail[:4000] + "…"
            raise CoreError(
                f"Core command failed ({process.returncode}): {detail}"
            )

        try:
            value = json.loads(process.stdout)
        except json.JSONDecodeError as exc:
            raise CoreError(
                "Core returned invalid JSON for "
                + shlex.join([*self.command, *arguments])
            ) from exc
        if not isinstance(value, dict):
            raise CoreError("Core JSON result is not an object")
        return value

    def list_runners(
        self,
        collection_root: Path,
    ) -> tuple[tuple[RunnerRecord, ...], tuple[str, ...]]:
        value = self.run_json(
            (
                "list-preserved-runners",
                "--collection-root",
                str(collection_root),
                "--json",
            )
        )
        if value.get("schema") != 0:
            raise CoreError("Unsupported runner catalog schema")
        raw_runners = value.get("runners")
        raw_warnings = value.get("warnings")
        if not isinstance(raw_runners, list) or not isinstance(
            raw_warnings,
            list,
        ):
            raise CoreError("Runner catalog fields are invalid")
        try:
            runners = tuple(
                RunnerRecord.from_dict(item)
                for item in raw_runners
                if isinstance(item, dict)
            )
        except ValueError as exc:
            raise CoreError(str(exc)) from exc
        if len(runners) != len(raw_runners):
            raise CoreError("Runner catalog contains a non-object entry")
        if any(not isinstance(item, str) for item in raw_warnings):
            raise CoreError("Runner warnings must be strings")
        return runners, tuple(raw_warnings)

    def list_component_sets(
        self,
        collection_root: Path,
    ) -> tuple[ComponentSet, ...]:
        value = self.run_json(
            (
                "list-shared-umu-runtimes",
                "--collection-root",
                str(collection_root),
                "--json",
            )
        )
        if value.get("schema") != 0:
            raise CoreError("Unsupported UMU component-set schema")
        raw = value.get("component_sets")
        if not isinstance(raw, list):
            raise CoreError("UMU component_sets is not an array")
        try:
            result = tuple(
                ComponentSet.from_dict(item)
                for item in raw
                if isinstance(item, dict)
            )
        except ValueError as exc:
            raise CoreError(str(exc)) from exc
        if len(result) != len(raw):
            raise CoreError(
                "UMU component catalog contains a non-object entry"
            )
        return result

    def discover_bottles_path(self) -> Path:
        value = self.run_json(("discover-bottles-path", "--json"))
        if value.get("schema") != 0:
            raise CoreError("Unsupported Bottles discovery schema")
        raw = value.get("bottles_path")
        if not isinstance(raw, str) or not raw:
            raise CoreError("Core did not return a Bottles path")
        return Path(raw)

    def verify_state_backup(
        self,
        *,
        capsule_path: Path,
        backup: Path,
    ) -> StateBackupRecord:
        value = self.run_json(
            (
                "verify-state-backup",
                "--capsule",
                str(capsule_path),
                "--backup",
                str(backup),
                "--json",
            )
        )
        if value.get("schema") != 0:
            raise CoreError(
                "Unsupported state-backup verification schema"
            )
        if value.get("verified") is not True:
            problems = value.get("problems", [])
            detail = (
                "; ".join(
                    item
                    for item in problems
                    if isinstance(item, str)
                )
                if isinstance(problems, list)
                else ""
            )
            raise CoreError(
                "State backup did not verify"
                + (f": {detail}" if detail else "")
            )

        backup_id = value.get("backup_id")
        backup_kind = value.get("backup_kind")
        if not isinstance(backup_id, str) or not backup_id:
            raise CoreError(
                "Verified state backup has no backup_id"
            )
        if not isinstance(backup_kind, str) or not backup_kind:
            raise CoreError(
                "Verified state backup has no backup_kind"
            )

        counts: dict[str, int] = {}
        for key in (
            "item_count",
            "present_count",
            "missing_count",
            "total_bytes",
        ):
            item = value.get(key)
            if (
                isinstance(item, bool)
                or not isinstance(item, int)
                or item < 0
            ):
                raise CoreError(
                    f"State-backup verification has invalid {key}"
                )
            counts[key] = item

        return StateBackupRecord(
            backup_id=backup_id,
            path=backup,
            backup_kind=backup_kind,
            item_count=counts["item_count"],
            present_count=counts["present_count"],
            missing_count=counts["missing_count"],
            total_bytes=counts["total_bytes"],
        )

    def compose(self, request: CompositionRequest) -> CompositionResult:
        arguments: list[str] = [
            "compose",
            "--collection-root",
            str(request.collection_root),
            "--capsule",
            str(request.capsule_path),
            "--backend",
            request.backend,
            "--runner",
            request.runner_id,
        ]

        if request.source_profile_id:
            arguments.extend(
                ("--source-profile", request.source_profile_id)
            )

        if request.no_state:
            if request.state_backup is not None:
                raise CoreError(
                    "--no-state and --state-backup are mutually exclusive"
                )
            arguments.append("--no-state")
        elif request.state_backup is not None:
            arguments.extend(
                ("--state-backup", str(request.state_backup))
            )

        if request.destination is None:
            raise CoreError("A materialization destination is required")
        arguments.extend(
            ("--destination", str(request.destination))
        )

        if request.backend == "bottles":
            if not request.bottle_name:
                raise CoreError("A Bottles derivative name is required")
            if request.arguments:
                raise CoreError(
                    "Additional game arguments are not supported for Bottles"
                )
            if request.bottles_path is not None:
                arguments.extend(
                    ("--bottles-path", str(request.bottles_path))
                )
            arguments.extend(("--bottle-name", request.bottle_name))

        if request.play:
            arguments.append("--play")
        arguments.append("--json")
        if request.arguments:
            arguments.append("--")
            arguments.extend(request.arguments)

        value = self.run_json(arguments, timeout=3600)
        try:
            return CompositionResult.from_dict(value)
        except ValueError as exc:
            raise CoreError(str(exc)) from exc

    def _run(
        self,
        arguments: Sequence[str],
        *,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                [*self.command, *arguments],
                env=dict(self.environment),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise CoreError("Core executable disappeared") from exc
        except subprocess.TimeoutExpired as exc:
            raise CoreError("Core command timed out") from exc
        except OSError as exc:
            raise CoreError(f"Could not execute core: {exc}") from exc
