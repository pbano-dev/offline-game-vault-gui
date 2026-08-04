from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .model import SaveSetItemRecord, SaveSetRecord


class SaveSetError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise SaveSetError(f"Not a regular JSON file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SaveSetError(f"Invalid JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SaveSetError(f"JSON root is not an object: {path}")
    return value


def _entries(document: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("save_sets", "entries", "sets"):
        value = document.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _text(mapping: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _integer(mapping: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, int) and value >= 0:
            return value
    return 0


def _safe_under(root: Path, value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise SaveSetError(f"Save-set path is not portable: {value}")
    resolved_root = root.resolve(strict=True)
    candidate = root.joinpath(*relative.parts)
    try:
        candidate.resolve(strict=False).relative_to(resolved_root)
    except ValueError as exc:
        raise SaveSetError(f"Save-set path escapes its root: {value}") from exc
    current = resolved_root
    for part in candidate.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            raise SaveSetError(
                f"Save-set path contains a symlink: {value}"
            )
        if not current.exists():
            break
    return candidate


def scan_save_sets(
    collection_root: Path,
    capsule_id: str,
) -> tuple[tuple[SaveSetRecord, ...], tuple[str, ...]]:
    root = (
        Path(collection_root)
        / "03_PERSISTENT_STATE"
        / capsule_id
        / "save-sets"
    )
    index = root / "index.json"
    if not index.exists():
        return (), ()
    document = _load_json(index)
    warnings: list[str] = []
    result: list[SaveSetRecord] = []
    for number, item in enumerate(_entries(document)):
        try:
            save_id = _text(item, "save_set_id", "id")
            if not save_id:
                raise SaveSetError("missing save_set_id")
            manifest_value = _text(
                item,
                "manifest",
                "manifest_path",
                "path",
            )
            manifest_path = (
                _safe_under(root, manifest_value)
                if manifest_value
                else index
            )
            manifest = (
                _load_json(manifest_path)
                if manifest_path != index
                else item
            )
            items_raw = manifest.get("items")
            if not isinstance(items_raw, list):
                items_raw = item.get("items", [])
            parsed_items: list[SaveSetItemRecord] = []
            if isinstance(items_raw, list):
                for entry in items_raw:
                    if not isinstance(entry, dict):
                        continue
                    payload_value = _text(
                        entry,
                        "payload",
                        "payload_path",
                        "archive",
                    )
                    payload = (
                        _safe_under(
                            manifest_path.parent,
                            payload_value,
                        )
                        if payload_value
                        else manifest_path
                    )
                    parsed_items.append(
                        SaveSetItemRecord(
                            state_id=_text(entry, "state_id", "id")
                            or "state",
                            declared_path=_text(
                                entry,
                                "declared_path",
                                "path",
                            ),
                            digest=_text(entry, "digest", "sha256")
                            .removeprefix("sha256:"),
                            size=_integer(entry, "bytes", "size"),
                            payload_path=payload,
                            entry_type=_text(entry, "entry_type", "type")
                            or "file",
                            file_count=_integer(entry, "file_count") or 1,
                            directory_count=_integer(
                                entry,
                                "directory_count",
                            ),
                        )
                    )
            manifest_digest = _text(
                item,
                "manifest_digest",
                "manifest_sha256",
            ).removeprefix("sha256:")
            if (
                not manifest_digest
                and manifest_path.is_file()
                and manifest_path != index
            ):
                manifest_digest = _sha256_file(manifest_path)
            result.append(
                SaveSetRecord(
                    capsule_id=capsule_id,
                    save_set_id=save_id,
                    display_name=_text(
                        item,
                        "display_name",
                        "label",
                        "name",
                    )
                    or save_id,
                    captured_at=_text(item, "captured_at", "created_at"),
                    captured_at_basis=_text(
                        item,
                        "captured_at_basis",
                    ),
                    aggregate_digest=_text(
                        item,
                        "aggregate_digest",
                        "digest",
                    ).removeprefix("sha256:"),
                    size=_integer(item, "bytes", "size"),
                    manifest_path=manifest_path,
                    manifest_digest=manifest_digest,
                    items=tuple(parsed_items),
                    status=_text(item, "status") or "candidate",
                    source=(
                        item.get("source")
                        if isinstance(item.get("source"), dict)
                        else None
                    ),
                )
            )
        except (SaveSetError, OSError) as exc:
            warnings.append(f"save-sets[{number}]: {exc}")
    result.sort(key=lambda item: (item.display_name.casefold(), item.save_set_id))
    return tuple(result), tuple(warnings)
