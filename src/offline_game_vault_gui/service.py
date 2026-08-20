from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time
from typing import Any, Sequence

from . import __version__
from .catalog import CapsuleCatalog
from .core import CoreClient, CoreError
from .model import (
    Backend,
    ComponentSet,
    CompositionRequest,
    CompositionResult,
    GameRecord,
    RunnerRecord,
    SaveSetRecord,
    StateBackupRecord,
    StateSelectionRecord,
)
from .save_sets import scan_save_sets


class ServiceError(RuntimeError):
    pass


PORTABLE_BOTTLE_NAME = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}"
)
OPERATIONS = {
    "play": "JUGAR.sh",
    "verify": "VERIFICAR.sh",
    "remove": "DESINSTALAR.sh",
}


class CompositionService:
    """Safety boundary between presentation and the authoritative core."""

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

    def save_sets(
        self,
        collection_root: Path,
        capsule_id: str,
    ) -> tuple[tuple[SaveSetRecord, ...], tuple[str, ...]]:
        root = self._regular_collection(collection_root)
        return scan_save_sets(root, capsule_id)

    def state_selections(
        self,
        collection_root: Path,
        game: GameRecord,
    ) -> tuple[
        tuple[StateSelectionRecord, ...],
        tuple[str, ...],
    ]:
        root = self._regular_collection(collection_root)
        save_sets, warnings = scan_save_sets(
            root,
            game.capsule_id,
        )
        warning_list = list(warnings)
        backup_root = (
            root
            / "03_PERSISTENT_STATE"
            / game.capsule_id
        )
        if not backup_root.exists():
            return (), tuple(warning_list)
        if backup_root.is_symlink() or not backup_root.is_dir():
            return (
                (),
                tuple(
                    [
                        *warning_list,
                        "Persistent-state root is not a regular directory",
                    ]
                ),
            )

        receipts = sorted(
            backup_root.rglob("state-backup.json")
        )
        if len(receipts) > 512:
            warning_list.append(
                "Persistent-state scan exceeded 512 candidate receipts"
            )
            receipts = receipts[:512]

        backups: list[StateBackupRecord] = []
        seen_paths: set[Path] = set()
        resolved_backup_root = backup_root.resolve(strict=True)
        for receipt in receipts:
            candidate = receipt.parent
            try:
                if (
                    receipt.is_symlink()
                    or not receipt.is_file()
                    or candidate.is_symlink()
                ):
                    raise ServiceError(
                        "candidate receipt or directory is linked or irregular"
                    )
                resolved = candidate.resolve(strict=True)
                resolved.relative_to(resolved_backup_root)
                current = resolved_backup_root
                for part in resolved.relative_to(current).parts:
                    current = current / part
                    if current.is_symlink():
                        raise ServiceError(
                            "candidate traverses a symbolic link"
                        )
                if resolved in seen_paths:
                    continue
                seen_paths.add(resolved)

                verified = self.core.verify_state_backup(
                    capsule_path=game.capsule_path,
                    backup=resolved,
                )
                receipt_document = json.loads(
                    receipt.read_text(encoding="utf-8")
                )
                if not isinstance(receipt_document, dict):
                    raise ServiceError(
                        "verified state-backup receipt is not an object"
                    )

                created_at = receipt_document.get("created_at", "")
                if not isinstance(created_at, str):
                    created_at = ""

                present_save_count = 0
                present_identity_count = 0
                items = receipt_document.get("items", [])
                if isinstance(items, list):
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        present = item.get("present") is True
                        file_count = item.get("file_count")
                        if (
                            not present
                            and isinstance(file_count, int)
                            and not isinstance(file_count, bool)
                            and file_count > 0
                        ):
                            present = True
                        if not present:
                            continue
                        kind = item.get("kind")
                        if kind == "save":
                            present_save_count += 1
                        elif kind == "identity":
                            present_identity_count += 1

                backups.append(
                    replace(
                        verified,
                        created_at=created_at,
                        present_save_count=present_save_count,
                        present_identity_count=present_identity_count,
                    )
                )
            except (
                json.JSONDecodeError,
                OSError,
                ValueError,
                CoreError,
                ServiceError,
            ) as exc:
                warning_list.append(
                    f"Ignored state backup {candidate.name!r}: {exc}"
                )

        linked: dict[Path, list[SaveSetRecord]] = {}
        for save_set in save_sets:
            resolved = save_set.backup_path(root)
            if resolved is None:
                warning_list.append(
                    f"Save set {save_set.save_set_id!r} has no linked "
                    "verified backup path"
                )
                continue
            linked.setdefault(resolved, []).append(save_set)

        selections: list[StateSelectionRecord] = []
        for backup in backups:
            matches = linked.get(backup.path, [])
            save_set_id: str | None = None
            if len(matches) == 1:
                display_name = (
                    f"{backup.display_date} — "
                    f"{matches[0].display_name}"
                )
                save_set_id = matches[0].save_set_id
            elif len(matches) > 1:
                display_name = (
                    f"{backup.display_date} — "
                    f"{backup.content_label}"
                )
                warning_list.append(
                    f"Several save sets reference backup "
                    f"{backup.backup_id!r}; provenance was not selected"
                )
            else:
                display_name = (
                    f"{backup.display_date} — "
                    f"{backup.content_label}"
                )
            selections.append(
                StateSelectionRecord(
                    backup=backup,
                    display_name=display_name,
                    save_set_id=save_set_id,
                )
            )

        selections.sort(
            key=lambda item: (
                item.backup.recency_key,
                item.backup.backup_id,
            ),
            reverse=True,
        )
        return tuple(selections), tuple(warning_list)

    def compatible_runners(
        self,
        runners: Sequence[RunnerRecord],
        backend: Backend,
    ) -> tuple[RunnerRecord, ...]:
        return tuple(
            item for item in runners if item.supports(backend)
        )

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
            raise ServiceError(
                "Core did not report a materialized derivative"
            )

        destination = result.destination.expanduser()
        self._operation_path(destination, "play")
        self._operation_path(destination, "verify")
        self._operation_path(destination, "remove")
        self._write_receipt(normalized, result)
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
            return subprocess.run(
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
            raise ServiceError(
                f"Could not execute {script.name}: {exc}"
            ) from exc

    def _validate_request(
        self,
        request: CompositionRequest,
    ) -> CompositionRequest:
        root = self._regular_collection(request.collection_root)

        capsule = request.capsule_path.expanduser()
        if capsule.is_symlink() or not capsule.is_file():
            raise ServiceError(
                "The selected capsule is not a regular file"
            )
        capsule = capsule.resolve()
        if not capsule.is_relative_to(root):
            raise ServiceError(
                "The selected capsule escapes the collection"
            )

        if request.backend not in {
            "bottles",
            "direct-wine",
            "umu",
        }:
            raise ServiceError("Unsupported backend")
        if not request.runner_id:
            raise ServiceError("A preserved runner is required")

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
            if bottles_path is not None:
                bottles_path = bottles_path.expanduser()
                if (
                    bottles_path.is_symlink()
                    or not bottles_path.is_dir()
                ):
                    raise ServiceError(
                        "The managed Bottles path is not a regular directory"
                    )
                bottles_path = bottles_path.resolve()
                if destination.is_relative_to(bottles_path):
                    raise ServiceError(
                        "The external Bottles destination must remain "
                        "outside the managed Bottles directory"
                    )

        state_backup = request.state_backup
        save_set_id = request.save_set_id
        umu_save_id = request.umu_save_id
        if umu_save_id is not None and request.backend != "umu":
            raise ServiceError(
                "UMU selectable state can only be used with the UMU backend"
            )
        if request.no_state and (
            state_backup is not None
            or save_set_id is not None
            or umu_save_id is not None
        ):
            raise ServiceError(
                "Starting without state cannot also restore/select state"
            )
        if state_backup is not None:
            state_backup = state_backup.expanduser()
            if (
                state_backup.is_symlink()
                or not state_backup.is_dir()
            ):
                raise ServiceError(
                    "The state backup is not a regular directory"
                )
            state_backup = state_backup.resolve()
            try:
                self.core.verify_state_backup(
                    capsule_path=capsule,
                    backup=state_backup,
                )
            except CoreError as exc:
                raise ServiceError(
                    f"The selected state backup is invalid: {exc}"
                ) from exc
        elif save_set_id is not None:
            raise ServiceError(
                "The selected save set has no usable state backup directory"
            )

        return CompositionRequest(
            collection_root=root,
            capsule_path=capsule,
            backend=request.backend,
            runner_id=request.runner_id,
            source_profile_id=request.source_profile_id,
            destination=destination,
            state_backup=state_backup,
            save_set_id=save_set_id,
            no_state=request.no_state,
            umu_save_id=umu_save_id,
            bottles_path=bottles_path,
            bottle_name=bottle_name,
            play=request.play,
            arguments=request.arguments,
        )

    def _regular_collection(self, path: Path) -> Path:
        path = path.expanduser()
        if path.is_symlink() or not path.is_dir():
            raise ServiceError(
                "The collection must be a regular directory"
            )
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

    def _write_receipt(
        self,
        request: CompositionRequest,
        result: CompositionResult,
    ) -> None:
        state_home = Path(
            os.environ.get(
                "XDG_STATE_HOME",
                str(Path.home() / ".local/state"),
            )
        ).expanduser()
        directory = (
            state_home
            / "offline-game-vault-gui"
            / "operations"
        )
        if directory.exists() and directory.is_symlink():
            raise ServiceError(
                "The local operation-receipt directory is a symlink"
            )
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)

        timestamp_ns = time.time_ns()
        path = directory / (
            f"{timestamp_ns}-{result.capsule_id}-{result.backend}.json"
        )
        document: dict[str, Any] = {
            "schema": 1,
            "record_type": "gui-composition-operation",
            "gui_version": __version__,
            "created_unix_ns": timestamp_ns,
            "request": {
                "capsule_id": result.capsule_id,
                "backend": request.backend,
                "runner_id": request.runner_id,
                "source_profile_id": request.source_profile_id,
                "save_set_id": request.save_set_id,
                "state_backup_selected": (
                    request.state_backup is not None
                ),
                "no_state_requested": request.no_state,
                "umu_save_id": request.umu_save_id,
                "play_requested": request.play,
            },
            "result": {
                "profile_id": result.profile_id,
                "materialized": result.materialized,
                "played": result.played,
                "play_complete": result.play_complete,
            },
        }

        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(
            json.dumps(
                document,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.chmod(0o600)
        os.replace(temporary, path)
