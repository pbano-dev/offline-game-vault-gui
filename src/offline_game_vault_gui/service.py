from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time
from typing import Any, Sequence

from .catalog import CapsuleCatalog
from .core import CoreClient
from .model import (
    Backend,
    ComponentSet,
    CompositionRequest,
    CompositionResult,
    GameRecord,
    RunnerRecord,
)


class ServiceError(RuntimeError):
    pass


PORTABLE_BOTTLE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


OPERATIONS = {
    "play": "JUGAR.sh",
    "verify": "VERIFICAR.sh",
    "remove": "DESINSTALAR.sh",
}


class CompositionService:
    def __init__(
        self,
        core: CoreClient,
        catalog: CapsuleCatalog | None = None,
    ) -> None:
        self.core = core
        self.catalog = catalog or CapsuleCatalog()

    def load(
        self,
        collection_root: Path,
    ) -> tuple[
        tuple[GameRecord, ...],
        tuple[RunnerRecord, ...],
        tuple[str, ...],
    ]:
        root = self._regular_collection(collection_root)
        games = self.catalog.scan(root)
        runners, warnings = self.core.list_runners(root)
        return games, runners, warnings

    def compatible_runners(
        self,
        runners: Sequence[RunnerRecord],
        backend: Backend,
    ) -> tuple[RunnerRecord, ...]:
        return tuple(item for item in runners if item.supports(backend))

    def component_sets(
        self,
        collection_root: Path,
    ) -> tuple[ComponentSet, ...]:
        return self.core.list_component_sets(
            self._regular_collection(collection_root)
        )

    def bottles_path(self) -> Path:
        return self.core.discover_bottles_path()

    def compose(
        self,
        request: CompositionRequest,
    ) -> CompositionResult:
        normalized = self._validate_request(request)
        result = self.core.compose(normalized)
        if not result.materialized:
            raise ServiceError("Core did not report a materialized derivative")
        destination = result.destination.expanduser()
        self._operation_path(destination, "play")
        self._operation_path(destination, "verify")
        self._operation_path(destination, "remove")
        self._write_local_receipt(normalized, result)
        return result

    def run_operation(
        self,
        destination: Path,
        operation: str,
        arguments: Sequence[str] = (),
    ) -> subprocess.CompletedProcess[str]:
        if operation not in OPERATIONS:
            raise ServiceError(f"Unknown operation: {operation}")
        if operation == "verify" and arguments:
            raise ServiceError(
                "Generated Verify does not accept additional arguments"
            )
        script = self._operation_path(destination, operation)
        try:
            process = subprocess.run(
                [str(script), *arguments],
                cwd=str(destination),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except OSError as exc:
            raise ServiceError(f"Could not execute {script.name}: {exc}") from exc
        return process

    def _validate_request(
        self,
        request: CompositionRequest,
    ) -> CompositionRequest:
        root = self._regular_collection(request.collection_root)
        capsule = request.capsule_path.expanduser()
        if capsule.is_symlink() or not capsule.is_file():
            raise ServiceError("The selected capsule is not a regular file")
        capsule = capsule.resolve()
        if not capsule.is_relative_to(root):
            raise ServiceError("The selected capsule escapes the collection")
        if request.backend not in {"bottles", "direct-wine", "umu"}:
            raise ServiceError("Unsupported backend")
        if not request.runner_id:
            raise ServiceError("A preserved runner is required")
        destination: Path | None = None
        bottles_path = request.bottles_path
        bottle_name = request.bottle_name
        if request.backend == "bottles":
            if (
                not bottle_name
                or PORTABLE_BOTTLE_NAME.fullmatch(bottle_name) is None
                or bottle_name in {".", ".."}
            ):
                raise ServiceError(
                    "A portable Bottles derivative name is required"
                )
            if request.arguments:
                raise ServiceError(
                    "Bottles does not accept additional game arguments"
                )
        else:
            if request.destination is None:
                raise ServiceError("A new destination is required")
            raw_destination = request.destination.expanduser()
            if raw_destination.name in {"", ".", ".."}:
                raise ServiceError("The destination name is invalid")
            if raw_destination.exists() or raw_destination.is_symlink():
                raise ServiceError("The destination already exists")
            parent = raw_destination.parent
            if parent.is_symlink() or not parent.is_dir():
                raise ServiceError(
                    "The destination parent must be a regular directory"
                )
            parent = parent.resolve()
            destination = parent / raw_destination.name
            if destination.is_relative_to(root):
                raise ServiceError(
                    "Writable derivatives must remain outside the collection"
                )
        state_backup = request.state_backup
        if state_backup is not None:
            state_backup = state_backup.expanduser()
            if state_backup.is_symlink() or not state_backup.is_dir():
                raise ServiceError(
                    "The Direct-Wine state backup is not a regular directory"
                )
            state_backup = state_backup.resolve()
        return CompositionRequest(
            collection_root=root,
            capsule_path=capsule,
            backend=request.backend,
            runner_id=request.runner_id,
            source_profile_id=request.source_profile_id,
            destination=destination,
            state_backup=state_backup,
            bottles_path=bottles_path,
            bottle_name=bottle_name,
            play=request.play,
            arguments=request.arguments,
        )

    def _regular_collection(self, path: Path) -> Path:
        path = path.expanduser()
        if path.is_symlink() or not path.is_dir():
            raise ServiceError("The collection must be a regular directory")
        return path.resolve()

    def _operation_path(
        self,
        destination: Path,
        operation: str,
    ) -> Path:
        if operation not in OPERATIONS:
            raise ServiceError(f"Unknown operation: {operation}")
        destination = destination.expanduser()
        if destination.is_symlink() or not destination.is_dir():
            raise ServiceError(
                "The materialization is not a regular directory"
            )
        root = destination.resolve()
        script = root / OPERATIONS[operation]
        try:
            info = script.lstat()
        except FileNotFoundError as exc:
            raise ServiceError(
                f"Generated operation is missing: {script.name}"
            ) from exc
        if (
            stat.S_ISLNK(info.st_mode)
            or not stat.S_ISREG(info.st_mode)
            or not info.st_mode & stat.S_IXUSR
            or script.resolve().parent != root
        ):
            raise ServiceError(
                f"Generated operation is unsafe: {script.name}"
            )
        return script

    def _write_local_receipt(
        self,
        request: CompositionRequest,
        result: CompositionResult,
    ) -> Path:
        state_home = Path(
            os.environ.get(
                "XDG_STATE_HOME",
                str(Path.home() / ".local/state"),
            )
        )
        directory = state_home / "offline-game-vault-gui" / "operations"
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        safe_capsule = "".join(
            character if character.isalnum() or character in "._-" else "_"
            for character in result.capsule_id
        )[:128]
        path = directory / f"{timestamp}-{safe_capsule}.json"
        backend_facts = {
            key: result.backend_result[key]
            for key in (
                "component_set_id",
                "backend_component_id",
                "runtime_component_id",
                "backend_entrypoint",
                "runner_installed",
            )
            if key in result.backend_result
            and isinstance(result.backend_result[key], (str, bool, int))
        }
        document: dict[str, Any] = {
            "schema": 1,
            "gui_version": "0.4.1",
            "capsule_id": result.capsule_id,
            "backend": result.backend,
            "runner_id": result.runner_id,
            "profile_id": result.profile_id,
            "destination": str(result.destination),
            "materialized": result.materialized,
            "played": result.played,
            "play_complete": result.play_complete,
            "backend_facts": backend_facts,
            "request": {
                "source_profile_id": request.source_profile_id,
                "bottle_name": request.bottle_name,
                "argument_count": len(request.arguments),
            },
        }
        path.write_text(
            json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        path.chmod(0o600)
        return path
