from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


class SharedBackendError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SharedBackendRecord:
    backend_id: str
    digest: str
    archive_path: str
    size: int
    label: str
    role: str
    application_ref: str
    application_commit: str
    version: str
    receipt_path: Path


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise SharedBackendError(f"{label} must be a regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SharedBackendError(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise SharedBackendError(f"{label} does not contain a JSON object")
    return value


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SharedBackendError(f"Missing valid text in {label}")
    return value.strip()


def scan_shared_bottles_backend(
    collection_root: Path,
) -> SharedBackendRecord:
    root = Path(collection_root)
    if root.is_symlink() or not root.is_dir():
        raise SharedBackendError("The collection is not a regular directory")
    root = root.resolve(strict=True)

    index = _load_json(root / "INDEX.json", "INDEX.json")
    inventory = _load_json(
        root / "01_IMMUTABLE_VAULT/VAULT_INVENTORY.json",
        "VAULT_INVENTORY.json",
    )

    index_objects = index.get("objects")
    inventory_objects = inventory.get("objects")
    if not isinstance(index_objects, list) or not isinstance(
        inventory_objects, list
    ):
        raise SharedBackendError("Inventory or index has no objects[]")

    candidates = [
        item
        for item in index_objects
        if isinstance(item, dict)
        and item.get("role") == "shared-backend"
        and isinstance(item.get("label"), str)
        and item["label"].startswith("bottles-flatpak-")
    ]
    if len(candidates) != 1:
        raise SharedBackendError(
            "Exactly one Bottles shared backend must exist"
        )

    item = candidates[0]
    digest = _required_text(item.get("sha256"), "INDEX.objects[].sha256")
    label = _required_text(item.get("label"), "INDEX.objects[].label")
    archive_path = _required_text(item.get("path"), "INDEX.objects[].path")
    size = item.get("size")
    if not isinstance(size, int) or size <= 0:
        raise SharedBackendError("Invalid shared-backend size")

    qualified = f"sha256:{digest}"
    inventory_matches = [
        entry
        for entry in inventory_objects
        if isinstance(entry, dict) and entry.get("digest") == qualified
    ]
    if len(inventory_matches) != 1:
        raise SharedBackendError(
            "The shared backend does not appear exactly once in the inventory"
        )
    inventory_item = inventory_matches[0]
    if (
        inventory_item.get("path") != archive_path
        or inventory_item.get("bytes") != size
    ):
        raise SharedBackendError(
            "INDEX.json and VAULT_INVENTORY.json disagree for Bottles"
        )

    object_path = root / "01_IMMUTABLE_VAULT" / archive_path
    if object_path.is_symlink() or not object_path.is_file():
        raise SharedBackendError(
            "The physical shared-backend object is not a regular file"
        )
    if object_path.stat().st_size != size:
        raise SharedBackendError(
            "The physical shared-backend size does not match"
        )

    receipts_root = root / "04_RECEIPTS/_collection/operations"
    matches: list[tuple[Path, dict[str, Any]]] = []
    if receipts_root.is_dir() and not receipts_root.is_symlink():
        for receipt_path in sorted(receipts_root.glob("*/receipt.json")):
            try:
                receipt = _load_json(receipt_path, str(receipt_path))
            except SharedBackendError:
                continue
            archive = receipt.get("archive")
            backend = receipt.get("backend")
            if (
                receipt.get("operation") == "add-shared-backend"
                and isinstance(archive, dict)
                and archive.get("digest") == qualified
                and isinstance(backend, dict)
                and backend.get("classification") == "shared-backend"
            ):
                matches.append((receipt_path, receipt))

    if len(matches) != 1:
        raise SharedBackendError(
            "No unique receipt exists for the Bottles shared backend"
        )

    receipt_path, receipt = matches[0]
    backend = receipt["backend"]
    backend_id = _required_text(backend.get("id"), "receipt.backend.id")
    application_ref = _required_text(
        backend.get("application_ref"),
        "receipt.backend.application_ref",
    )
    application_commit = _required_text(
        backend.get("application_commit"),
        "receipt.backend.application_commit",
    )
    version = _required_text(backend.get("version"), "receipt.backend.version")

    if len(application_commit) != 64 or any(
        char not in "0123456789abcdef" for char in application_commit
    ):
        raise SharedBackendError(
            "The preserved Flatpak commit is not hexadecimal SHA-256"
        )

    return SharedBackendRecord(
        backend_id=backend_id,
        digest=qualified,
        archive_path=archive_path,
        size=size,
        label=label,
        role="shared-backend",
        application_ref=application_ref,
        application_commit=application_commit,
        version=version,
        receipt_path=receipt_path,
    )


def validate_shared_backend_record(
    collection_root: Path,
    expected: SharedBackendRecord,
) -> None:
    current = scan_shared_bottles_backend(collection_root)
    if current != expected:
        raise SharedBackendError(
            "The Bottles shared backend changed after catalog loading"
        )
