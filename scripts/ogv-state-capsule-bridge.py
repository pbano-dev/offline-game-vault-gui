#!/usr/bin/env python3
"""State-safe compatibility bridge for Direct-Wine runner overlays.

OfflineGameVault 1ed3b9c binds persistent-state verification and restoration
to the same capsule passed to materialize-playable. A runner overlay changes
the playable contract but not the persistent-state declarations. This bridge
keeps the derived capsule for object/layout/launcher construction and binds
only verify_state_backup/restore_state to the original capsule that created
the accepted backup.

The original capsule, backup, Vault, and runner objects are never modified.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable


class BridgeError(RuntimeError):
    pass


def _regular_file(path: Path, label: str) -> Path:
    candidate = path.expanduser()
    if candidate.is_symlink() or not candidate.is_file():
        raise BridgeError(f"{label} is not a regular file")
    return candidate.resolve(strict=True)


def _regular_directory(path: Path, label: str) -> Path:
    candidate = path.expanduser()
    if candidate.is_symlink() or not candidate.is_dir():
        raise BridgeError(f"{label} is not a regular directory")
    return candidate.resolve(strict=True)


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BridgeError(f"{label} does not contain valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise BridgeError(f"{label} does not contain a JSON object")
    return value


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _prepare_core_import() -> None:
    """Locate the source checkout used by the GUI, or an installed package."""
    configured = os.environ.get("OGV_SOURCE_ROOT")
    candidates: list[Path] = []

    if configured:
        candidates.append(Path(configured).expanduser())

    gui_root = Path(__file__).resolve().parent.parent
    candidates.append(gui_root / "../../git/offline-game-vault")

    for candidate in candidates:
        try:
            root = candidate.resolve(strict=True)
        except FileNotFoundError:
            continue
        source = root / "src"
        if (
            not root.is_dir()
            or root.is_symlink()
            or not (root / "pyproject.toml").is_file()
            or not (source / "offline_game_vault/playable.py").is_file()
        ):
            continue
        sys.path.insert(0, str(source))
        return

    try:
        importlib.import_module("offline_game_vault.playable")
    except ModuleNotFoundError as exc:
        raise BridgeError(
            "The offline-game-vault core was not found; "
            "configure OGV_SOURCE_ROOT"
        ) from exc


def _same_state_contract(
    original: dict[str, Any],
    derived: dict[str, Any],
) -> None:
    original_id = original.get("capsule_id")
    derived_id = derived.get("capsule_id")
    if not isinstance(original_id, str) or original_id != derived_id:
        raise BridgeError(
            "The original and derived capsules do not have the same capsule_id"
        )

    original_state = original.get("persistent_state", [])
    derived_state = derived.get("persistent_state", [])
    if _canonical(original_state) != _canonical(derived_state):
        raise BridgeError(
            "The overlay changed persistent_state; the accepted backup cannot be reused"
            ""
        )


def _proxy_with_original_capsule(
    original_function: Callable[..., Any],
    *,
    derived_capsule: Path,
    state_capsule: Path,
    label: str,
) -> Callable[..., Any]:
    def proxy(*args: Any, **kwargs: Any) -> Any:
        if args:
            raise BridgeError(
                f"Incompatible core API in {label}: positional arguments"
            )
        requested = kwargs.get("capsule_path")
        if requested is None:
            raise BridgeError(
                f"Incompatible core API in {label}: missing capsule_path"
            )
        requested_path = Path(requested).expanduser().resolve(strict=True)
        if requested_path != derived_capsule:
            raise BridgeError(
                f"{label} attempted to use a capsule different from the validated overlay"
            )
        forwarded = dict(kwargs)
        forwarded["capsule_path"] = state_capsule
        return original_function(**forwarded)

    return proxy


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ogv-state-capsule-bridge",
        description=(
            "Materialize a derived profile while using the original capsule "
            "exclusively to verify and restore persistent state."
        ),
    )
    parser.add_argument("command", choices=["materialize-playable"])
    parser.add_argument("--capsule", required=True, type=Path)
    parser.add_argument("--state-capsule", required=True, type=Path)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--vault-root", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--state-backup", required=True, type=Path)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    try:
        derived_capsule = _regular_file(args.capsule, "derived capsule")
        state_capsule = _regular_file(
            args.state_capsule,
            "original capsule for persistent state",
        )
        vault_root = _regular_directory(args.vault_root, "vault-root")
        state_backup = _regular_directory(
            args.state_backup,
            "state-backup",
        )

        original_document = _load_json(
            state_capsule,
            "original capsule",
        )
        derived_document = _load_json(
            derived_capsule,
            "derived capsule",
        )
        _same_state_contract(original_document, derived_document)

        _prepare_core_import()
        playable = importlib.import_module("offline_game_vault.playable")

        required = (
            "materialize_playable_profile",
            "verify_state_backup",
            "restore_state",
        )
        missing = [name for name in required if not hasattr(playable, name)]
        if missing:
            raise BridgeError(
                "The core does not expose the required API: " + ", ".join(missing)
            )

        original_verify = playable.verify_state_backup
        original_restore = playable.restore_state

        playable.verify_state_backup = _proxy_with_original_capsule(
            original_verify,
            derived_capsule=derived_capsule,
            state_capsule=state_capsule,
            label="verify_state_backup",
        )
        playable.restore_state = _proxy_with_original_capsule(
            original_restore,
            derived_capsule=derived_capsule,
            state_capsule=state_capsule,
            label="restore_state",
        )

        try:
            result = playable.materialize_playable_profile(
                capsule_path=derived_capsule,
                profile_id=args.profile,
                vault_root=vault_root,
                destination=args.destination,
                state_backup=state_backup,
            )
        finally:
            playable.verify_state_backup = original_verify
            playable.restore_state = original_restore

        payload = result.to_dict()
        if not isinstance(payload, dict):
            raise BridgeError("The core returned a non-serializable result")

        print(
            json.dumps(
                {"materialization": payload},
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0

    except Exception as exc:
        print(
            f"ogv-state-capsule-bridge: error: {exc}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
