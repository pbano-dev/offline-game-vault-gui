from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any

from .model import SaveSetItemRecord, SaveSetRecord


class SaveSetCatalogError(RuntimeError):
    pass


_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise SaveSetCatalogError(
            f"{label} must be a regular file"
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SaveSetCatalogError(
            f"{label} does not contain valid JSON: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise SaveSetCatalogError(
            f"{label} does not contain a JSON object"
        )
    return value


def _required_text(
    mapping: dict[str, Any],
    key: str,
    context: str,
) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SaveSetCatalogError(
            f"{context}: missing valid text in {key!r}"
        )
    return value.strip()


def _safe_relative(value: Any, label: str) -> PurePosixPath:
    if (
        not isinstance(value, str)
        or not value
        or "\x00" in value
        or "\\" in value
    ):
        raise SaveSetCatalogError(
            f"{label} is not a portable relative path"
        )
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise SaveSetCatalogError(
            f"{label} is not a safe relative path"
        )
    return path


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _save_declarations(
    capsule_path: Path,
    capsule_id: str,
) -> dict[str, dict[str, Any]]:
    capsule = _load_json(capsule_path, "capsule.json")
    if capsule.get("capsule_id") != capsule_id:
        raise SaveSetCatalogError(
            "capsule_id does not match while reading save sets"
        )

    state = capsule.get("persistent_state", [])
    if not isinstance(state, list):
        raise SaveSetCatalogError(
            "persistent_state is not an array"
        )

    result: dict[str, dict[str, Any]] = {}
    for item in state:
        if not isinstance(item, dict):
            raise SaveSetCatalogError(
                "persistent_state contains an invalid entry"
            )
        if item.get("kind") != "save":
            continue
        state_id = _required_text(
            item,
            "id",
            "save declaration",
        )
        if state_id in result:
            raise SaveSetCatalogError(
                f"duplicate save declaration: {state_id}"
            )
        result[state_id] = item

    return result


def _definition_digest(declaration: dict[str, Any]) -> str:
    normalized = {
        "id": declaration.get("id"),
        "path": declaration.get("path"),
        "kind": declaration.get("kind"),
        "backup": declaration.get("backup", True),
        "sensitive": declaration.get("sensitive", False),
        "required": declaration.get("required", True),
    }

    for key in ("id", "path", "kind"):
        value = normalized[key]
        if not isinstance(value, str) or not value:
            raise SaveSetCatalogError(
                f"save declaration: {key} is not valid text"
            )

    for key in ("backup", "sensitive", "required"):
        if not isinstance(normalized[key], bool):
            raise SaveSetCatalogError(
                f"save declaration: {key} is not boolean"
            )

    payload = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _aggregate_digest(items: list[SaveSetItemRecord]) -> str:
    payload = json.dumps(
        [
            {
                "state_id": item.state_id,
                "declared_path": item.declared_path,
                "digest": item.digest,
                "bytes": item.size,
                "entry_type": item.entry_type,
            }
            for item in items
        ],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _validate_payload(
    *,
    save_set_id: str,
    item: dict[str, Any],
    manifest_path: Path,
) -> SaveSetItemRecord:
    state_id = _required_text(item, "state_id", f"{save_set_id}.item")
    declared_path = _required_text(
        item, "declared_path", f"{save_set_id}.{state_id}"
    )
    digest = _required_text(item, "digest", f"{save_set_id}.{state_id}")
    if not _DIGEST_RE.fullmatch(digest):
        raise SaveSetCatalogError(f"{save_set_id}: invalid digest for {state_id}")

    size = item.get("bytes")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise SaveSetCatalogError(f"{save_set_id}: invalid byte count for {state_id}")

    entry_type = item.get("entry_type", "file")
    if entry_type not in {"file", "directory"}:
        raise SaveSetCatalogError(
            f"{save_set_id}: unsupported entry_type for {state_id}"
        )
    payload_relative = _safe_relative(
        item.get("payload_path"),
        f"{save_set_id}.{state_id}.payload_path",
    )
    payload_path = (
        manifest_path.parent.joinpath(*payload_relative.parts)
    ).resolve(strict=False)
    if not _within(payload_path, manifest_path.parent) or payload_path.is_symlink():
        raise SaveSetCatalogError(
            f"{save_set_id}: unsafe payload for {state_id}"
        )

    file_count = item.get("file_count", 1 if entry_type == "file" else 0)
    directory_count = item.get(
        "directory_count", 0 if entry_type == "file" else 1
    )
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in (file_count, directory_count)
    ):
        raise SaveSetCatalogError(
            f"{save_set_id}: invalid counters for {state_id}"
        )

    if entry_type == "file":
        if not payload_path.is_file():
            raise SaveSetCatalogError(
                f"{save_set_id}: missing file payload for {state_id}"
            )
        metadata = payload_path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise SaveSetCatalogError(
                f"{save_set_id}: unsafe file payload for {state_id}"
            )
        if metadata.st_size != size:
            raise SaveSetCatalogError(
                f"{save_set_id}: incorrect physical size for {state_id}"
            )
        if "sha256:" + _sha256(payload_path) != digest:
            raise SaveSetCatalogError(
                f"{save_set_id}: incorrect physical hash for {state_id}"
            )
    else:
        if not payload_path.is_dir():
            raise SaveSetCatalogError(
                f"{save_set_id}: missing directory payload for {state_id}"
            )
        files = 0
        directories = 1
        total = 0
        for candidate in payload_path.rglob("*"):
            if candidate.is_symlink():
                raise SaveSetCatalogError(
                    f"{save_set_id}: directory contains a symbolic link for {state_id}"
                )
            info = candidate.lstat()
            if stat.S_ISDIR(info.st_mode):
                directories += 1
            elif stat.S_ISREG(info.st_mode):
                if info.st_nlink != 1:
                    raise SaveSetCatalogError(
                        f"{save_set_id}: hard link in payload for {state_id}"
                    )
                files += 1
                total += info.st_size
            else:
                raise SaveSetCatalogError(
                    f"{save_set_id}: unsupported payload type for {state_id}"
                )
        if (files, directories, total) != (
            file_count,
            directory_count,
            size,
        ):
            raise SaveSetCatalogError(
                f"{save_set_id}: inconsistent physical inventory for {state_id}"
            )
        # Directory digests are produced from a canonical tree manifest. The
        # save-set manifest is itself sealed and the full tree is checked here;
        # the exact tree digest is recomputed later when composing accepted.

    return SaveSetItemRecord(
        state_id=state_id,
        declared_path=declared_path,
        digest=digest,
        size=size,
        payload_path=payload_path,
        entry_type=entry_type,
        file_count=file_count,
        directory_count=directory_count,
    )


def _parse_entry(
    *,
    collection_root: Path,
    save_root: Path,
    capsule_id: str,
    declarations: dict[str, dict[str, Any]],
    entry: dict[str, Any],
) -> SaveSetRecord:
    save_set_id = _required_text(
        entry, "save_set_id", "save-sets/index.json"
    )
    status = str(entry.get("status", "")).strip()
    if status not in {"verified", "candidate"}:
        raise SaveSetCatalogError(
            f"{save_set_id}: status is not candidate/verified"
        )

    manifest_relative = _safe_relative(
        entry.get("manifest"), f"{save_set_id}.manifest"
    )
    manifest_path = save_root.joinpath(*manifest_relative.parts).resolve(
        strict=False
    )
    if (
        not _within(manifest_path, save_root)
        or manifest_path.is_symlink()
        or not manifest_path.is_file()
    ):
        raise SaveSetCatalogError(
            f"{save_set_id}: manifest is unsafe or missing"
        )
    actual_manifest_digest = _sha256(manifest_path)
    if entry.get("manifest_sha256") != actual_manifest_digest:
        raise SaveSetCatalogError(
            f"{save_set_id}: incorrect manifest hash"
        )

    manifest = _load_json(manifest_path, f"{save_set_id}/save-set.json")
    manifest_status = str(manifest.get("status", "")).strip()
    if manifest_status not in {"verified", "candidate"}:
        raise SaveSetCatalogError(
            f"{save_set_id}: manifest is not candidate/verified"
        )
    if manifest_status != status:
        raise SaveSetCatalogError(
            f"{save_set_id}: status differs between index and manifest"
        )
    if manifest.get("capsule_id") != capsule_id:
        raise SaveSetCatalogError(
            f"{save_set_id}: inconsistent capsule_id"
        )
    if manifest.get("save_set_id") != save_set_id:
        raise SaveSetCatalogError(
            f"{save_set_id}: inconsistent save_set_id"
        )

    raw_items = manifest.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise SaveSetCatalogError(
            f"{save_set_id}: manifest contains no items"
        )

    records: list[SaveSetItemRecord] = []
    seen: set[str] = set()
    for raw_item in raw_items:
        if not isinstance(raw_item, dict) or raw_item.get("kind") != "save":
            raise SaveSetCatalogError(
                f"{save_set_id}: item is not kind=save"
            )
        item_record = _validate_payload(
            save_set_id=save_set_id,
            item=raw_item,
            manifest_path=manifest_path,
        )
        if item_record.state_id in seen:
            raise SaveSetCatalogError(
                f"{save_set_id}: duplicate state_id"
            )
        seen.add(item_record.state_id)
        declaration = declarations.get(item_record.state_id)
        if declaration is None:
            raise SaveSetCatalogError(
                f"{save_set_id}: {item_record.state_id} does not resolve to kind=save"
            )
        if declaration.get("path") != item_record.declared_path:
            raise SaveSetCatalogError(
                f"{save_set_id}: declared_path does not match for "
                f"{item_record.state_id}"
            )

        definitions = manifest.get("save_definition_digests")
        if isinstance(definitions, dict):
            expected = definitions.get(item_record.state_id)
        else:
            # v1 compatibility.
            expected = manifest.get("save_definition_digest")
        if expected != _definition_digest(declaration):
            raise SaveSetCatalogError(
                f"{save_set_id}: save definition does not match for "
                f"{item_record.state_id}"
            )
        records.append(item_record)

    state_ids = entry.get("state_ids")
    if state_ids is None and len(records) == 1:
        state_ids = [entry.get("state_id")]
    if state_ids != [item.state_id for item in records]:
        raise SaveSetCatalogError(
            f"{save_set_id}: inconsistent state_ids"
        )
    if entry.get("item_count", len(records)) != len(records):
        raise SaveSetCatalogError(
            f"{save_set_id}: inconsistent item_count"
        )

    total_size = sum(item.size for item in records)
    if entry.get("bytes", total_size) != total_size:
        raise SaveSetCatalogError(
            f"{save_set_id}: index byte count is inconsistent"
        )
    aggregate = manifest.get("aggregate_digest")
    if not isinstance(aggregate, str):
        # v1 aggregate is the single item digest.
        aggregate = records[0].digest if len(records) == 1 else _aggregate_digest(records)
    if not _DIGEST_RE.fullmatch(aggregate):
        raise SaveSetCatalogError(
            f"{save_set_id}: invalid aggregate_digest"
        )
    entry_aggregate = entry.get("aggregate_digest")
    if entry_aggregate is not None and entry_aggregate != aggregate:
        raise SaveSetCatalogError(
            f"{save_set_id}: inconsistent aggregate_digest"
        )

    display_name = _required_text(
        manifest, "display_name", f"{save_set_id}/save-set.json"
    )
    if entry.get("display_name") != display_name:
        raise SaveSetCatalogError(
            f"{save_set_id}: inconsistent display_name"
        )
    captured_at = _required_text(
        manifest, "captured_at", f"{save_set_id}/save-set.json"
    )
    captured_at_basis = _required_text(
        manifest, "captured_at_basis", f"{save_set_id}/save-set.json"
    )
    if (
        entry.get("captured_at") != captured_at
        or entry.get("captured_at_basis") != captured_at_basis
    ):
        raise SaveSetCatalogError(
            f"{save_set_id}: date differs between index and manifest"
        )

    source = manifest.get("source")
    if source is not None and not isinstance(source, dict):
        raise SaveSetCatalogError(
            f"{save_set_id}: source is not an object"
        )

    return SaveSetRecord(
        capsule_id=capsule_id,
        save_set_id=save_set_id,
        display_name=display_name,
        captured_at=captured_at,
        captured_at_basis=captured_at_basis,
        aggregate_digest=aggregate,
        size=total_size,
        manifest_path=manifest_path,
        manifest_digest="sha256:" + actual_manifest_digest,
        items=tuple(records),
        status=status,
        source=source,
    )


def scan_save_sets(
    collection_root: Path,
    *,
    capsule_path: Path,
    capsule_id: str,
) -> tuple[tuple[SaveSetRecord, ...], tuple[str, ...]]:
    root = Path(collection_root)
    if root.is_symlink() or not root.is_dir():
        raise SaveSetCatalogError(
            "The collection is not a regular directory"
        )
    root = root.resolve(strict=True)

    contract = _load_json(
        root
        / "03_PERSISTENT_STATE"
        / "SAVE_LIBRARY_CONTRACT.json",
        "SAVE_LIBRARY_CONTRACT.json",
    )
    if contract.get("contract") not in {
        "ogv-save-library-v1",
        "ogv-save-library-v2",
    }:
        raise SaveSetCatalogError(
            "Unrecognized save library contract"
        )
    if contract.get("default_selection") != "none":
        raise SaveSetCatalogError(
            "The default save selection is not none"
        )

    capsule_path = Path(capsule_path)
    if capsule_path.is_symlink() or not capsule_path.is_file():
        raise SaveSetCatalogError(
            "capsule.json is not a regular file"
        )
    capsule_path = capsule_path.resolve(strict=True)

    declarations = _save_declarations(
        capsule_path,
        capsule_id,
    )
    if not declarations:
        return (), ()

    save_root = (
        root
        / "03_PERSISTENT_STATE"
        / capsule_id
        / "save-sets"
    )
    if save_root.is_symlink() or not save_root.is_dir():
        raise SaveSetCatalogError(
            f"{capsule_id}: regular save-sets directory is missing"
        )
    save_root = save_root.resolve(strict=True)

    index = _load_json(
        save_root / "index.json",
        f"{capsule_id}/save-sets/index.json",
    )
    if index.get("capsule_id") != capsule_id:
        raise SaveSetCatalogError(
            "Save index capsule_id does not match"
        )
    if index.get("selection_policy") != "explicit-only":
        raise SaveSetCatalogError(
            "Selection policy is not explicit-only"
        )
    if index.get("default_save_set_id") is not None:
        raise SaveSetCatalogError(
            "The index declares a default save set"
        )
    if index.get("status") not in {"verified", "candidate"}:
        raise SaveSetCatalogError(
            "The save index is not candidate/verified"
        )

    raw_entries = index.get("entries")
    if not isinstance(raw_entries, list):
        raise SaveSetCatalogError(
            "save-sets/index.json contains no entries[]"
        )

    records: list[SaveSetRecord] = []
    warnings: list[str] = []
    seen: set[str] = set()

    for raw in raw_entries:
        if not isinstance(raw, dict):
            warnings.append(
                f"{capsule_id}: save-set entry is not an object"
            )
            continue
        try:
            record = _parse_entry(
                collection_root=root,
                save_root=save_root,
                capsule_id=capsule_id,
                declarations=declarations,
                entry=raw,
            )
        except SaveSetCatalogError as exc:
            warnings.append(str(exc))
            continue
        if record.save_set_id in seen:
            warnings.append(
                f"{capsule_id}: duplicate save_set_id "
                f"{record.save_set_id}"
            )
            continue
        seen.add(record.save_set_id)
        records.append(record)

    records.sort(
        key=lambda item: (
            item.captured_at,
            item.save_set_id,
        ),
        reverse=True,
    )

    expected_count = index.get("save_set_count")
    if (
        isinstance(expected_count, int)
        and expected_count != len(raw_entries)
    ):
        warnings.append(
            f"{capsule_id}: save_set_count does not match "
            "entries[]"
        )

    return tuple(records), tuple(warnings)


def validate_save_set_record(
    collection_root: Path,
    *,
    capsule_path: Path,
    expected: SaveSetRecord,
) -> None:
    records, warnings = scan_save_sets(
        collection_root,
        capsule_path=capsule_path,
        capsule_id=expected.capsule_id,
    )
    matches = [
        record
        for record in records
        if record.save_set_id == expected.save_set_id
    ]
    if len(matches) != 1 or matches[0] != expected:
        detail = "; ".join(warnings)
        suffix = f": {detail}" if detail else ""
        raise SaveSetCatalogError(
            "The selected save set changed after catalog loading"
            f"{suffix}"
        )
