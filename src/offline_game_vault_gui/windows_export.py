from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import uuid
from typing import Any

from .model import SaveSetRecord
from .neutral_profiles import (
    NeutralProfileError,
    load_neutral_contract,
    resolve_neutral_materialized_paths,
    windows_state_destination,
)


class WindowsExportError(RuntimeError):
    pass


def _safe_relative(value: Any, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise WindowsExportError(f"{label} is not a portable relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise WindowsExportError(f"{label} is not a safe relative path")
    return path


def _copy_payload(source: Path, destination: Path) -> None:
    if source.is_symlink():
        raise WindowsExportError("state payload is a symbolic link")
    if source.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination, follow_symlinks=False)
    elif source.is_dir():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination, symlinks=False)
    else:
        raise WindowsExportError("state payload is not regular")


def _powershell_script() -> str:
    return '''$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Map = Get-Content -LiteralPath (Join-Path $Root "STATE_MAP.json") -Raw |
    ConvertFrom-Json
foreach ($Item in $Map.items) {
    $Target = [Environment]::ExpandEnvironmentVariables($Item.windows_destination)
    $Target = $Target.Replace("%OGV_EXPORT_ROOT%", $Root)
    $Source = Join-Path $Root $Item.source
    $Parent = Split-Path -Parent $Target
    New-Item -ItemType Directory -Force -Path $Parent | Out-Null
    if ($Item.entry_type -eq "directory") {
        if (Test-Path -LiteralPath $Target) {
            Remove-Item -LiteralPath $Target -Recurse -Force
        }
        Copy-Item -LiteralPath $Source -Destination $Target -Recurse -Force
    } else {
        Copy-Item -LiteralPath $Source -Destination $Target -Force
    }
    Write-Host ("Installed: " + $Target)
}
'''


def transform_base_to_windows_export(
    *,
    materialization: Path,
    capsule_path: Path,
    profile_id: str,
    capsule_id: str,
    save_set: SaveSetRecord | None,
    state_backup: Path | None = None,
) -> dict[str, Any]:
    contract = load_neutral_contract(
        capsule_path,
        profile_id,
        expected_contract="ogv-windows-export-v1",
    )
    if contract is None:
        raise WindowsExportError(
            "The Windows profile does not declare ogv-windows-export-v1"
        )
    document = contract.document
    entrypoint = _safe_relative(
        document.get("entrypoint_relative_to_game"),
        "entrypoint_relative_to_game",
    )

    root = materialization.resolve(strict=True)
    try:
        _neutral, _prefix, source_game = resolve_neutral_materialized_paths(
            materialization=root,
            document=document,
            require_prefix=False,
        )
    except NeutralProfileError as exc:
        raise WindowsExportError(str(exc)) from exc

    old_receipt = root / "materialization-receipt.json"
    old_receipt_payload = (
        old_receipt.read_bytes()
        if old_receipt.is_file() and not old_receipt.is_symlink()
        else None
    )

    staging = root.parent / f".{root.name}.windows-{uuid.uuid4().hex}"
    staging.mkdir(mode=0o700)
    try:
        shutil.copytree(source_game, staging / "game", symlinks=False)
        state_root = staging / "selected-state"
        state_root.mkdir()
        state_entries: list[dict[str, Any]] = []
        if state_backup is not None:
            backup_root = Path(state_backup)
            if backup_root.is_symlink() or not backup_root.is_dir():
                raise WindowsExportError("the state backup is not a regular directory")
            receipt_path = backup_root / "state-backup.json"
            if receipt_path.is_symlink() or not receipt_path.is_file():
                raise WindowsExportError("a regular state-backup.json is missing")
            try:
                backup_receipt = json.loads(
                    receipt_path.read_text(encoding="utf-8")
                )
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise WindowsExportError(
                    f"state-backup.json is invalid: {exc}"
                ) from exc
            if (
                not isinstance(backup_receipt, dict)
                or backup_receipt.get("capsule_id") != capsule_id
                or backup_receipt.get("complete") is not True
            ):
                raise WindowsExportError("the state backup does not belong to the capsule")
            backup_items = backup_receipt.get("items")
            if not isinstance(backup_items, list):
                raise WindowsExportError("the state backup contains no items[]")
            backup_root_resolved = backup_root.resolve(strict=True)
            for index, item in enumerate(backup_items):
                if not isinstance(item, dict) or item.get("present") is not True:
                    continue
                state_id = item.get("id")
                declared_path = item.get("declared_path")
                payload_raw = item.get("payload_path")
                if not all(
                    isinstance(value, str) and value
                    for value in (state_id, declared_path, payload_raw)
                ):
                    raise WindowsExportError("present state item is incomplete")
                payload_rel = _safe_relative(payload_raw, f"{state_id}.payload_path")
                source = backup_root.joinpath(*payload_rel.parts)
                if source.is_symlink() or not source.exists():
                    raise WindowsExportError(
                        f"{state_id}: state payload is missing or a symbolic link"
                    )
                try:
                    source.resolve(strict=True).relative_to(backup_root_resolved)
                except ValueError as exc:
                    raise WindowsExportError(
                        f"{state_id}: state payload escapes the backup"
                    ) from exc
                destination = state_root / f"{index:04d}-{state_id}" / "data"
                _copy_payload(source, destination)
                state_entries.append({
                    "state_id": state_id,
                    "source": destination.relative_to(staging).as_posix(),
                    "declared_path": declared_path,
                    "windows_destination": windows_state_destination(
                        declared_path
                    ),
                    "entry_type": item.get("entry_type", "file"),
                    "digest": item.get("tree_digest"),
                    "bytes": item.get("bytes", 0),
                    "kind": item.get("kind", "other"),
                })
        elif save_set is not None:
            # Compatibility path for direct callers. The normal service path
            # passes the already composed accepted backup.
            for index, item in enumerate(save_set.items):
                destination = state_root / f"{index:04d}-{item.state_id}" / "data"
                _copy_payload(item.payload_path, destination)
                state_entries.append({
                    "state_id": item.state_id,
                    "source": destination.relative_to(staging).as_posix(),
                    "declared_path": item.declared_path,
                    "windows_destination": windows_state_destination(
                        item.declared_path
                    ),
                    "entry_type": item.entry_type,
                    "digest": item.digest,
                    "bytes": item.size,
                    "kind": "save",
                })

        state_map = {
            "schema": 0,
            "contract": "ogv-windows-state-map-v1",
            "capsule_id": capsule_id,
            "profile_id": profile_id,
            "save_set_id": (
                save_set.save_set_id if save_set is not None else None
            ),
            "items": state_entries,
        }
        (staging / "STATE_MAP.json").write_text(
            json.dumps(state_map, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (staging / "INSTALL_STATE.ps1").write_text(
            _powershell_script(),
            encoding="utf-8",
            newline="\r\n",
        )
        windows_entrypoint = entrypoint.as_posix().replace("/", "\\")
        launcher = (
            "@echo off\r\n"
            "setlocal\r\n"
            'cd /d "%~dp0game"\r\n'
            f'start "" "{windows_entrypoint}"\r\n'
        )
        (staging / "PLAY.cmd").write_text(
            launcher,
            encoding="utf-8",
            newline="",
        )
        readme = (
            "# Candidate Windows export\n\n"
            "1. Run `INSTALL_STATE.ps1` from PowerShell when a save set was selected"
            ".\n"
            "2. Run `PLAY.cmd`.\n\n"
            "Status: not tested on Windows. This export contains no Wine, "
            "Bottles, or Linux prefix.\n"
        )
        (staging / "00_README.md").write_text(readme, encoding="utf-8")
        if old_receipt_payload is not None:
            evidence = staging / "evidence"
            evidence.mkdir()
            (evidence / "source-materialization-receipt.json").write_bytes(
                old_receipt_payload
            )

        receipt = {
            "schema": 0,
            "contract": "ogv-windows-export-receipt-v1",
            "capsule_id": capsule_id,
            "profile_id": profile_id,
            "save_set_id": (
                save_set.save_set_id if save_set is not None else None
            ),
            "entrypoint": f"game/{entrypoint.as_posix()}",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "candidate-not-tested",
            "game_tree_present": True,
            "state_item_count": len(state_entries),
            "prefix_included": False,
            "runner_included": False,
            "bottles_metadata_included": False,
            "host_contract_sha256": hashlib.sha256(
                contract.path.read_bytes()
            ).hexdigest(),
        }
        (staging / "windows-export-receipt.json").write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        old = root.parent / f".{root.name}.base-old-{uuid.uuid4().hex}"
        os.replace(root, old)
        try:
            os.replace(staging, root)
        except Exception:
            os.replace(old, root)
            raise
        shutil.rmtree(old)
        return receipt
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
