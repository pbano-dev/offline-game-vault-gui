from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import shutil
import stat
from typing import Any, Iterator
import uuid

from . import __version__
from .model import SaveSetRecord, ValidatedRequest
from .save_sets import (
    SaveSetCatalogError,
    validate_save_set_record,
)


class StateSelectionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PreparedStateBackup:
    backup_path: Path | None
    workspace: Path | None
    save_set_id: str | None
    save_digest: str | None
    label: str

    @property
    def snapshot_path(self) -> Path | None:
        if self.workspace is None:
            return None
        return self.workspace / "pre-restore-snapshot"


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise StateSelectionError(
            f"{label} must be a regular file"
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StateSelectionError(
            f"{label} does not contain valid JSON: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise StateSelectionError(
            f"{label} does not contain a JSON object"
        )
    return value


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _tree_digest(entries: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        entries,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _safe_relative(value: Any, label: str) -> PurePosixPath:
    if (
        not isinstance(value, str)
        or not value
        or "\x00" in value
        or "\\" in value
    ):
        raise StateSelectionError(
            f"{label} is not a portable relative path"
        )
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise StateSelectionError(
            f"{label} is not a safe relative path"
        )
    return path


def _normalized_declarations(
    capsule: dict[str, Any],
) -> list[dict[str, Any]]:
    raw = capsule.get("persistent_state", [])
    if not isinstance(raw, list):
        raise StateSelectionError(
            "persistent_state is not an array"
        )

    result: list[dict[str, Any]] = []
    seen: set[str] = set()

    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise StateSelectionError(
                f"persistent_state[{index}] is not an object"
            )
        declaration = {
            "id": item.get("id"),
            "path": item.get("path"),
            "kind": item.get("kind"),
            "backup": item.get("backup", True),
            "sensitive": item.get("sensitive", False),
            "required": item.get("required", True),
        }
        if any(
            not isinstance(declaration[key], str)
            or not declaration[key]
            for key in ("id", "path", "kind")
        ):
            raise StateSelectionError(
                f"persistent_state[{index}] contains invalid text"
            )
        if any(
            not isinstance(declaration[key], bool)
            for key in ("backup", "sensitive", "required")
        ):
            raise StateSelectionError(
                f"persistent_state[{index}] contains invalid boolean values"
            )
        state_id = str(declaration["id"])
        if state_id in seen:
            raise StateSelectionError(
                f"persistent_state contains a duplicate id: {state_id}"
            )
        seen.add(state_id)
        result.append(declaration)

    # The OGV core normalizes persistent_state by id before creating and
    # verify accepted/state-backup.json. The capsule may keep a different
    # documentary order; composition must follow OGV's contractual order,
    # not the source array order.
    return [
        item
        for item in sorted(
            result,
            key=lambda declaration: str(declaration["id"]),
        )
        if item["backup"] is True
    ]


def _private_copytree(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_dir():
        raise StateSelectionError(
            "The accepted backup is not a regular directory"
        )

    shutil.copytree(
        source,
        destination,
        symlinks=False,
        copy_function=shutil.copy2,
    )

    for path in [
        destination,
        *destination.rglob("*"),
    ]:
        if path.is_symlink():
            raise StateSelectionError(
                "The accepted backup contains a symbolic link"
            )
        if path.is_dir():
            os.chmod(path, 0o700)
        elif path.is_file():
            if path.lstat().st_nlink != 1:
                raise StateSelectionError(
                    "The temporary copy contains hard links"
                )
            os.chmod(path, 0o600)
        else:
            raise StateSelectionError(
                "The accepted backup contains an unsupported type"
            )


def _copy_selected_item(
    *,
    selected: Any,
    declaration: dict[str, Any],
    index: int,
    payload_root: Path,
) -> dict[str, Any]:
    state_id = selected.state_id
    container = payload_root / f"{index:04d}-{state_id}"
    if container.exists() or container.is_symlink():
        if container.is_symlink():
            raise StateSelectionError(
                "The accepted save container is a symbolic link"
            )
        shutil.rmtree(container)
    container.mkdir(mode=0o700)
    data_path = container / "data"

    entries: list[dict[str, Any]] = []
    if selected.entry_type == "file":
        shutil.copyfile(
            selected.payload_path,
            data_path,
            follow_symlinks=False,
        )
        os.chmod(data_path, 0o600)
        metadata = data_path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise StateSelectionError(
                f"{state_id}: temporary payload is not a private file"
            )
        digest = "sha256:" + hashlib.sha256(data_path.read_bytes()).hexdigest()
        if metadata.st_size != selected.size or digest != selected.digest:
            raise StateSelectionError(
                f"{state_id}: temporary payload changed"
            )
        entries = [{
            "path": ".",
            "type": "file",
            "mode": 0o600,
            "bytes": selected.size,
            "digest": selected.digest,
        }]
        file_count = 1
        directory_count = 0
        total = selected.size
    elif selected.entry_type == "directory":
        if selected.payload_path.is_symlink() or not selected.payload_path.is_dir():
            raise StateSelectionError(
                f"{state_id}: directory payload is not regular"
            )
        shutil.copytree(
            selected.payload_path,
            data_path,
            symlinks=False,
            copy_function=shutil.copy2,
        )
        os.chmod(data_path, 0o700)
        file_count = 0
        directory_count = 0
        total = 0
        for path in sorted(
            data_path.rglob("*"),
            key=lambda candidate: candidate.relative_to(data_path).as_posix(),
        ):
            if path.is_symlink():
                raise StateSelectionError(
                    f"{state_id}: payload contains symbolic links"
                )
            relative = path.relative_to(data_path).as_posix()
            info = path.lstat()
            if stat.S_ISDIR(info.st_mode):
                directory_count += 1
                os.chmod(path, 0o700)
                entries.append({
                    "path": relative,
                    "type": "directory",
                    "mode": 0o700,
                })
            elif stat.S_ISREG(info.st_mode):
                if info.st_nlink != 1:
                    raise StateSelectionError(
                        f"{state_id}: payload contains hard links"
                    )
                os.chmod(path, 0o600)
                file_count += 1
                total += info.st_size
                entries.append({
                    "path": relative,
                    "type": "file",
                    "mode": 0o600,
                    "bytes": info.st_size,
                    "digest": "sha256:" + hashlib.sha256(
                        path.read_bytes()
                    ).hexdigest(),
                })
            else:
                raise StateSelectionError(
                    f"{state_id}: unsupported type in payload"
                )
        if (
            file_count != selected.file_count
            or directory_count != selected.directory_count
            or total != selected.size
        ):
            raise StateSelectionError(
                f"{state_id}: inconsistent temporary inventory"
            )
        if _tree_digest(entries) != selected.digest:
            raise StateSelectionError(
                f"{state_id}: inconsistent temporary tree digest"
            )
    else:
        raise StateSelectionError(
            f"{state_id}: unsupported entry_type"
        )

    return {
        "id": declaration["id"],
        "declared_path": declaration["path"],
        "kind": declaration["kind"],
        "sensitive": declaration["sensitive"],
        "required": declaration["required"],
        "present": True,
        "entry_type": selected.entry_type,
        "payload_path": f"payload/{index:04d}-{state_id}/data",
        "file_count": file_count,
        "directory_count": directory_count,
        "bytes": total,
        "tree_digest": _tree_digest(entries),
        "entries": entries,
    }


def _compose_selected_backup(
    *,
    request: ValidatedRequest,
    destination: Path,
) -> Path:
    save_set = request.save_set
    accepted = request.state_backup
    if save_set is None or accepted is None:
        raise StateSelectionError(
            "No composable state selection exists"
        )

    try:
        validate_save_set_record(
            request.collection_root,
            capsule_path=request.capsule_path,
            expected=save_set,
        )
    except SaveSetCatalogError as exc:
        raise StateSelectionError(str(exc)) from exc

    _private_copytree(accepted, destination)
    capsule = _load_json(request.capsule_path, "capsule.json")
    if capsule.get("capsule_id") != request.capsule_id:
        raise StateSelectionError(
            "capsule_id does not match while composing state"
        )
    declarations = _normalized_declarations(capsule)
    declaration_by_id = {
        str(item["id"]): (index, item)
        for index, item in enumerate(declarations)
    }

    receipt_path = destination / "state-backup.json"
    receipt = _load_json(receipt_path, "accepted/state-backup.json")
    if receipt.get("capsule_id") != request.capsule_id:
        raise StateSelectionError(
            "The accepted backup belongs to another capsule"
        )
    if receipt.get("complete") is not True:
        raise StateSelectionError(
            "The accepted backup is not complete"
        )
    items = receipt.get("items")
    if not isinstance(items, list):
        raise StateSelectionError(
            "The accepted backup contains no items[]"
        )
    expected_ids = [str(item["id"]) for item in declarations]
    actual_ids = [
        item.get("id") for item in items if isinstance(item, dict)
    ]
    if actual_ids != expected_ids:
        raise StateSelectionError(
            "The accepted item order does not match persistent_state"
        )

    payload_root = destination / "payload"
    if payload_root.is_symlink() or not payload_root.is_dir():
        raise StateSelectionError(
            "The accepted backup does not contain a regular payload"
        )

    selected_ids = set()
    for selected in save_set.items:
        if selected.state_id in selected_ids:
            raise StateSelectionError(
                "The save set contains duplicate state_id values"
            )
        selected_ids.add(selected.state_id)
        resolved = declaration_by_id.get(selected.state_id)
        if resolved is None:
            raise StateSelectionError(
                f"{selected.state_id}: does not resolve to persistent_state"
            )
        index, declaration = resolved
        if declaration["kind"] != "save":
            raise StateSelectionError(
                f"{selected.state_id}: is not kind=save"
            )
        if selected.declared_path != declaration["path"]:
            raise StateSelectionError(
                f"{selected.state_id}: declared_path does not match"
            )
        items[index] = _copy_selected_item(
            selected=selected,
            declaration=declaration,
            index=index,
            payload_root=payload_root,
        )

    receipt["backup_id"] = f"state-backup-{uuid.uuid4()}"
    receipt["created_at"] = datetime.now(timezone.utc).isoformat()
    receipt["orchestrator_version"] = (
        f"offline-game-vault-gui-{__version__}"
    )
    receipt["backup_kind"] = "preserved"
    receipt["stopped_confirmed"] = True
    receipt["complete"] = True
    receipt["items"] = items
    receipt_path.write_bytes(_canonical_json(receipt))
    os.chmod(receipt_path, 0o600)
    os.chmod(payload_root, 0o700)
    os.chmod(destination, 0o700)
    return destination


@contextmanager
def prepared_state_backup(
    request: ValidatedRequest,
) -> Iterator[PreparedStateBackup]:
    if request.state_backup is None:
        if request.save_set is not None:
            raise StateSelectionError(
                "A save set was selected, but the capsule "
                "declares no restorable state"
            )
        yield PreparedStateBackup(
            backup_path=None,
            workspace=None,
            save_set_id=None,
            save_digest=None,
            label="No persistent state",
        )
        return

    parent = request.destination_parent
    workspace = parent / (
        f".ogv-state-selection-{request.capsule_id}-"
        f"{os.getpid()}-{secrets.token_hex(8)}"
    )
    if workspace.exists() or workspace.is_symlink():
        raise StateSelectionError(
            "The temporary state workspace already exists"
        )
    workspace.mkdir(mode=0o700)

    try:
        if request.save_set is None:
            prepared = PreparedStateBackup(
                backup_path=request.state_backup,
                workspace=workspace,
                save_set_id=None,
                save_digest=None,
                label="No save",
            )
        else:
            backup = _compose_selected_backup(
                request=request,
                destination=workspace / "state-backup",
            )
            prepared = PreparedStateBackup(
                backup_path=backup,
                workspace=workspace,
                save_set_id=request.save_set.save_set_id,
                save_digest=request.save_set.digest,
                label=request.save_set.display_name,
            )

        yield prepared
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
