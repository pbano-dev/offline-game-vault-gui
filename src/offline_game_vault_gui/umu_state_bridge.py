from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .model import SaveSetItemRecord, SaveSetRecord
from .umu_model import UmuSelection


_SAVE_ID_RE = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")


class UmuStateBridgeError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PreparedDerivedState:
    state_root: Path | None
    state_archives: tuple[dict[str, str], ...]
    protected_manifests: tuple[dict[str, str], ...]
    mutable_paths: tuple[str, ...]
    selected_save_id: str | None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise UmuStateBridgeError(
            f"Cannot hash state payload: {path}"
        ) from exc
    return digest.hexdigest()


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise UmuStateBridgeError(
            f"{label} is absent or not a regular file"
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise UmuStateBridgeError(
            f"{label} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise UmuStateBridgeError(
            f"{label} does not contain a JSON object"
        )
    return value


def _safe_relative(value: str, label: str) -> PurePosixPath:
    if (
        not isinstance(value, str)
        or not value
        or "\x00" in value
        or "\\" in value
    ):
        raise UmuStateBridgeError(
            f"{label} is not a safe relative path"
        )
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise UmuStateBridgeError(
            f"{label} is not a safe relative path"
        )
    return path


def _under(root: Path, value: str, label: str) -> Path:
    relative = _safe_relative(value, label)
    candidate = root.joinpath(*relative.parts)
    try:
        candidate.resolve(strict=False).relative_to(
            root.resolve(strict=True)
        )
    except (OSError, ValueError) as exc:
        raise UmuStateBridgeError(
            f"{label} escapes its root"
        ) from exc
    return candidate


def _parse_digest(value: Any, label: str) -> str:
    if isinstance(value, str):
        value = value.removeprefix("sha256:")
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise UmuStateBridgeError(
            f"{label} is not a lowercase SHA-256"
        )
    return value


def _materialized_prefix(selection: UmuSelection) -> PurePosixPath:
    playable = selection.profile.original_profile.get("playable")
    if not isinstance(playable, dict):
        raise UmuStateBridgeError(
            "Direct-Wine source profile has no playable contract"
        )
    paths = playable.get("paths")
    if not isinstance(paths, dict):
        raise UmuStateBridgeError(
            "Direct-Wine source profile has no playable paths"
        )
    value = paths.get("prefix")
    if not isinstance(value, str):
        raise UmuStateBridgeError(
            "Direct-Wine source profile has no prefix path"
        )
    return _safe_relative(value, "playable.paths.prefix")


def _destination_path(
    prefix: PurePosixPath,
    declared_path: str,
) -> str:
    declared = _safe_relative(
        declared_path,
        "persistent-state declared path",
    )
    if declared.parts[: len(prefix.parts)] == prefix.parts:
        return declared.as_posix()
    return (prefix / declared).as_posix()


def _verify_regular_payload(
    item: SaveSetItemRecord,
) -> Path:
    path = item.payload_path
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise UmuStateBridgeError(
            f"Save payload is unavailable: {item.state_id}"
        ) from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
    ):
        raise UmuStateBridgeError(
            f"Save payload is not a regular file: {item.state_id}"
        )
    if item.entry_type not in {"", "file"}:
        raise UmuStateBridgeError(
            "Directory save-set items are not yet supported by the "
            f"UMU bridge: {item.state_id}"
        )
    if item.size and metadata.st_size != item.size:
        raise UmuStateBridgeError(
            f"Save payload size mismatch: {item.state_id}"
        )
    expected = _parse_digest(
        item.digest,
        f"save-set item {item.state_id}.digest",
    )
    if _sha256_file(path) != expected:
        raise UmuStateBridgeError(
            f"Save payload digest mismatch: {item.state_id}"
        )
    return path


def _add_parent_directories(
    archive: tarfile.TarFile,
    member_name: str,
    added: set[str],
) -> None:
    path = PurePosixPath(member_name)
    parents = list(path.parents)
    parents.reverse()
    for parent in parents:
        value = parent.as_posix()
        if value in {".", ""} or value in added:
            continue
        info = tarfile.TarInfo(value)
        info.type = tarfile.DIRTYPE
        info.mode = 0o755
        info.uid = 0
        info.gid = 0
        info.uname = ""
        info.gname = ""
        info.mtime = 0
        archive.addfile(info)
        added.add(value)


def _write_save_archive(
    *,
    selection: UmuSelection,
    save_set: SaveSetRecord,
    state_root: Path,
    prefix: PurePosixPath,
) -> tuple[dict[str, str], tuple[str, ...], str]:
    if _SAVE_ID_RE.fullmatch(save_set.save_set_id) is None:
        raise UmuStateBridgeError(
            f"Save-set ID is not portable: {save_set.save_set_id}"
        )
    if save_set.capsule_id != selection.profile.capsule_id:
        raise UmuStateBridgeError(
            "Selected save set belongs to another capsule"
        )
    if not save_set.items:
        raise UmuStateBridgeError(
            "Selected save set has no payload items"
        )
    if save_set.manifest_digest:
        actual_manifest = _sha256_file(save_set.manifest_path)
        if actual_manifest != save_set.manifest_digest:
            raise UmuStateBridgeError(
                "Save-set manifest digest mismatch"
            )

    filename = f"save-{save_set.save_set_id}.tar"
    archive_path = state_root / filename
    protected_lines: list[str] = []
    mutable_paths: list[str] = []
    added: set[str] = set()

    with tarfile.open(
        archive_path,
        mode="w",
        format=tarfile.PAX_FORMAT,
    ) as archive:
        for item in sorted(
            save_set.items,
            key=lambda value: (
                value.declared_path,
                value.state_id,
            ),
        ):
            source = _verify_regular_payload(item)
            destination = _destination_path(
                prefix,
                item.declared_path,
            )
            if destination in added:
                raise UmuStateBridgeError(
                    f"Duplicate save destination: {destination}"
                )
            _add_parent_directories(
                archive,
                destination,
                added,
            )
            metadata = source.stat()
            info = tarfile.TarInfo(destination)
            info.size = metadata.st_size
            info.mode = stat.S_IMODE(metadata.st_mode)
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.mtime = 0
            with source.open("rb") as handle:
                archive.addfile(info, handle)
            added.add(destination)
            digest = _sha256_file(source)
            protected_lines.append(
                f"{digest}  {destination}\n"
            )
            mutable_paths.append(destination)

    archive_digest = _sha256_file(archive_path)
    manifest_relative = (
        f"manifests/save-{save_set.save_set_id}.sha256"
    )
    manifest_path = state_root.parent / manifest_relative
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        "".join(protected_lines),
        encoding="utf-8",
        newline="\n",
    )
    return (
        {
            "id": save_set.save_set_id,
            "filename": filename,
            "digest": f"sha256:{archive_digest}",
            "policy": "selectable",
        },
        tuple(mutable_paths),
        manifest_relative,
    )


def _required_state_manifest(
    *,
    selection: UmuSelection,
    overlay_root: Path,
    prefix: PurePosixPath,
) -> str | None:
    capsule_state = selection.profile.capsule.get(
        "persistent_state",
        [],
    )
    required_ids = {
        item.get("id")
        for item in capsule_state
        if (
            isinstance(item, dict)
            and item.get("required") is True
            and isinstance(item.get("id"), str)
            and item.get("kind") != "save"
        )
    }
    if not required_ids:
        return None

    root = selection.profile.accepted_state_root
    if root is None:
        raise UmuStateBridgeError(
            "A selected save requires preserved identity/configuration, "
            "but the accepted state root is unavailable"
        )
    backup_path = root / "state-backup.json"
    backup = _load_json(
        backup_path,
        "accepted state-backup.json",
    )
    raw_items = backup.get("items")
    if not isinstance(raw_items, list):
        raise UmuStateBridgeError(
            "Accepted state backup has no items array"
        )
    by_id = {
        item.get("id"): item
        for item in raw_items
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }

    lines: list[str] = []
    for state_id in sorted(required_ids):
        item = by_id.get(state_id)
        if not isinstance(item, dict) or item.get("present") is not True:
            raise UmuStateBridgeError(
                f"Required accepted state is unavailable: {state_id}"
            )
        if item.get("entry_type") != "file":
            raise UmuStateBridgeError(
                "Directory required-state items are not yet supported by "
                f"the UMU bridge: {state_id}"
            )
        payload_value = item.get("payload_path")
        declared_value = item.get("declared_path")
        if not isinstance(payload_value, str) or not isinstance(
            declared_value,
            str,
        ):
            raise UmuStateBridgeError(
                f"Required accepted state is incomplete: {state_id}"
            )
        source = _under(
            root,
            payload_value,
            f"accepted state payload {state_id}",
        )
        try:
            metadata = source.lstat()
        except OSError as exc:
            raise UmuStateBridgeError(
                f"Required accepted-state payload is absent: {state_id}"
            ) from exc
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
        ):
            raise UmuStateBridgeError(
                f"Required accepted-state payload is not regular: {state_id}"
            )
        entries = item.get("entries")
        if not isinstance(entries, list):
            raise UmuStateBridgeError(
                f"Required accepted-state entries are absent: {state_id}"
            )
        file_entries = [
            entry
            for entry in entries
            if (
                isinstance(entry, dict)
                and entry.get("type") == "file"
                and entry.get("path") == "."
            )
        ]
        if len(file_entries) != 1:
            raise UmuStateBridgeError(
                f"Required accepted-state digest is ambiguous: {state_id}"
            )
        expected = _parse_digest(
            file_entries[0].get("digest"),
            f"accepted state {state_id}.digest",
        )
        expected_bytes = file_entries[0].get("bytes")
        if (
            isinstance(expected_bytes, int)
            and metadata.st_size != expected_bytes
        ):
            raise UmuStateBridgeError(
                f"Required accepted-state size mismatch: {state_id}"
            )
        if _sha256_file(source) != expected:
            raise UmuStateBridgeError(
                f"Required accepted-state digest mismatch: {state_id}"
            )
        destination = _destination_path(
            prefix,
            declared_value,
        )
        lines.append(f"{expected}  {destination}\n")

    relative = "manifests/required-state.sha256"
    destination = overlay_root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        "".join(lines),
        encoding="utf-8",
        newline="\n",
    )
    return relative


def prepare_derived_state(
    selection: UmuSelection,
    overlay_root: Path,
) -> PreparedDerivedState:
    if selection.profile.kind != "derived-wine":
        raise UmuStateBridgeError(
            "The save-set bridge only supports derived Direct-Wine profiles"
        )
    selected = selection.save_set
    if selected is None:
        if selection.save_id is not None:
            raise UmuStateBridgeError(
                "Derived UMU selection has a save ID but no save-set record"
            )
        return PreparedDerivedState(
            state_root=None,
            state_archives=(),
            protected_manifests=(),
            mutable_paths=(),
            selected_save_id=None,
        )
    if selection.save_id != selected.save_set_id:
        raise UmuStateBridgeError(
            "Selected save ID and save-set record do not match"
        )

    prefix = _materialized_prefix(selection)
    state_root = overlay_root / "state"
    state_root.mkdir(parents=True, mode=0o700)

    archive, mutable_paths, save_manifest = _write_save_archive(
        selection=selection,
        save_set=selected,
        state_root=state_root,
        prefix=prefix,
    )
    required_manifest = _required_state_manifest(
        selection=selection,
        overlay_root=overlay_root,
        prefix=prefix,
    )

    protected: list[dict[str, str]] = []
    if required_manifest is not None:
        protected.append({"source": required_manifest})
    protected.append(
        {
            "source": save_manifest,
            "when_save": selected.save_set_id,
        }
    )

    return PreparedDerivedState(
        state_root=state_root,
        state_archives=(archive,),
        protected_manifests=tuple(protected),
        mutable_paths=mutable_paths,
        selected_save_id=selected.save_set_id,
    )
