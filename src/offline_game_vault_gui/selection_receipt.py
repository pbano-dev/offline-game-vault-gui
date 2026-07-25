from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
from typing import Any

from . import __version__
from .model import SaveSetRecord


class SelectionReceiptError(RuntimeError):
    pass


DIRECT_RELATIVE = Path(
    "metadata/ogv-gui-state-selection.json"
)
DERIVATIVE_RELATIVE = Path(
    ".ogv-gui-state-selection.json"
)


def _document(
    *,
    capsule_id: str,
    profile_id: str,
    backend_id: str,
    runner_id: str | None,
    save_set: SaveSetRecord | None,
) -> dict[str, Any]:
    return {
        "schema": 0,
        "kind": "ogv-gui-state-selection",
        "created_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "gui_version": __version__,
        "capsule_id": capsule_id,
        "profile_id": profile_id,
        "backend_id": backend_id,
        "runner_id": runner_id,
        "selection": (
            "save-set" if save_set is not None else "none"
        ),
        "save_set_id": (
            save_set.save_set_id
            if save_set is not None
            else None
        ),
        "save_digest": (
            save_set.digest
            if save_set is not None
            else None
        ),
        "save_manifest_digest": (
            save_set.manifest_digest
            if save_set is not None
            else None
        ),
        "complete": True,
    }


def _atomic_json(path: Path, value: object) -> None:
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file():
            raise SelectionReceiptError(
                "The existing selection receipt is not regular"
            )

    data = (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    temporary = path.parent / (
        f".{path.name}.{os.getpid()}-"
        f"{secrets.token_hex(8)}.tmp"
    )
    temporary.write_text(data, encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def write_selection_receipt(
    root: Path,
    *,
    relative: Path,
    capsule_id: str,
    profile_id: str,
    backend_id: str,
    runner_id: str | None,
    save_set: SaveSetRecord | None,
) -> Path:
    base = Path(root)
    if base.is_symlink() or not base.is_dir():
        raise SelectionReceiptError(
            "The derived root is not a regular directory"
        )
    path = base / relative
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    _atomic_json(
        path,
        _document(
            capsule_id=capsule_id,
            profile_id=profile_id,
            backend_id=backend_id,
            runner_id=runner_id,
            save_set=save_set,
        ),
    )
    return path


def selection_receipt_matches(
    root: Path,
    *,
    relative: Path,
    capsule_id: str,
    profile_id: str,
    backend_id: str,
    runner_id: str | None,
    save_set: SaveSetRecord | None,
    allow_legacy_none: bool,
) -> bool:
    path = Path(root) / relative

    if not path.exists() and not path.is_symlink():
        return allow_legacy_none and save_set is None
    if path.is_symlink() or not path.is_file():
        return False

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False

    if not isinstance(value, dict):
        return False
    if (
        value.get("schema") != 0
        or value.get("kind") != "ogv-gui-state-selection"
        or value.get("complete") is not True
        or value.get("capsule_id") != capsule_id
        or value.get("profile_id") != profile_id
        or value.get("backend_id") != backend_id
        or value.get("runner_id") != runner_id
    ):
        return False

    if save_set is None:
        return (
            value.get("selection") == "none"
            and value.get("save_set_id") is None
            and value.get("save_digest") is None
            and value.get("save_manifest_digest") is None
        )

    return (
        value.get("selection") == "save-set"
        and value.get("save_set_id")
        == save_set.save_set_id
        and value.get("save_digest") == save_set.digest
        and value.get("save_manifest_digest")
        == save_set.manifest_digest
    )
