from __future__ import annotations

import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
from typing import Any

from offline_game_vault_gui.model import RunnerRecord
from offline_game_vault_gui.runners import scan_runners
from offline_game_vault_gui.save_sets import scan_save_sets
from offline_game_vault_gui.shared_backend import (
    scan_shared_bottles_backend,
)


CAPSULE_ID = "steam-1-test-1.0"
PROFILE_ID = "linux-direct-wine"
BOTTLES_PROFILE_ID = "linux-bottles-flatpak"
GE_RUNNER_ID = "ge-proton11-1"
SODA_RUNNER_ID = "soda-9.0-1"
BOTTLES_APP_REF = "app/com.usebottles.bottles/x86_64/stable"
BOTTLES_APP_COMMIT = "b" * 64


def _canonical_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _compact_digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _tar_gz(path: Path, root_name: str, files: dict[str, tuple[bytes, int]]) -> tuple[str, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tf:
                root_info = tarfile.TarInfo(root_name)
                root_info.type = tarfile.DIRTYPE
                root_info.mode = 0o755
                root_info.mtime = 1
                root_info.uid = root_info.gid = 0
                tf.addfile(root_info)

                directories: set[str] = set()
                for relative in files:
                    parts = relative.split("/")[:-1]
                    current: list[str] = []
                    for part in parts:
                        current.append(part)
                        directories.add("/".join(current))
                for directory in sorted(directories):
                    info = tarfile.TarInfo(f"{root_name}/{directory}")
                    info.type = tarfile.DIRTYPE
                    info.mode = 0o755
                    info.mtime = 1
                    info.uid = info.gid = 0
                    tf.addfile(info)

                for relative, (payload, mode) in sorted(files.items()):
                    info = tarfile.TarInfo(f"{root_name}/{relative}")
                    info.type = tarfile.REGTYPE
                    info.mode = mode
                    info.mtime = 1
                    info.uid = info.gid = 0
                    info.size = len(payload)
                    tf.addfile(info, io.BytesIO(payload))

    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest(), len(data)


def _object_path(digest: str) -> str:
    return f"objects/sha256/{digest[:2]}/{digest[2:4]}/{digest}"


def create_collection(root: Path) -> tuple[Path, Path]:
    root.mkdir()
    immutable = root / "01_IMMUTABLE_VAULT"
    objects_root = immutable / "objects/sha256"
    objects_root.mkdir(parents=True)

    object_specs: list[dict[str, Any]] = []

    def add_object(
        label: str,
        role: str,
        root_name: str,
        files: dict[str, tuple[bytes, int]],
    ) -> dict[str, Any]:
        temporary = root / f".{label}.tar.gz"
        digest, size = _tar_gz(temporary, root_name, files)
        relative = _object_path(digest)
        destination = immutable / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary.replace(destination)
        record = {
            "label": f"{label}.tar.gz",
            "path": relative,
            "role": role,
            "sha256": digest,
            "size": size,
        }
        object_specs.append(record)
        return {
            "id": label,
            "digest": f"sha256:{digest}",
            "archive_path": relative,
            "format": "tar.gz",
            "size": size,
            "source_root": root_name,
        }

    baseline = add_object(
        "baseline",
        "game-and-prefix-baseline",
        "Game",
        {
            "bottle.yml": (
                b'Name: "Game"\nPath: "Game"\nCustom_Path: false\n'
                b'Runner: "ge-proton11-1"\n',
                0o600,
            ),
            "drive_c/Games/Test/game.exe": (b"fixture-game\n", 0o755),
            "drive_c/save.dat": (b"save\n", 0o600),
        },
    )
    ge = add_object(
        GE_RUNNER_ID,
        "shared-runner",
        GE_RUNNER_ID,
        {
            "files/bin/wine": (b"fixture-ge-wine\n", 0o755),
            "files/bin/wineserver": (b"fixture-ge-wineserver\n", 0o755),
        },
    )
    soda = add_object(
        SODA_RUNNER_ID,
        "shared-runner",
        SODA_RUNNER_ID,
        {
            "bin/wine": (b"fixture-soda-wine\n", 0o755),
            "bin/wineserver": (b"fixture-soda-wineserver\n", 0o755),
        },
    )

    backend_payload = b"fixture-bottles-flatpak-sideload\n"
    backend_digest = hashlib.sha256(backend_payload).hexdigest()
    backend_relative = _object_path(backend_digest)
    backend_destination = immutable / backend_relative
    backend_destination.parent.mkdir(parents=True, exist_ok=True)
    backend_destination.write_bytes(backend_payload)
    backend = {
        "label": "bottles-flatpak-64.1-x86_64-stable.tar.zst",
        "path": backend_relative,
        "role": "shared-backend",
        "sha256": backend_digest,
        "size": len(backend_payload),
    }
    object_specs.append(backend)

    inventory_objects = [
        {
            "bytes": item["size"],
            "digest": f"sha256:{item['sha256']}",
            "path": item["path"],
        }
        for item in object_specs
    ]
    _canonical_json(
        immutable / "VAULT_INVENTORY.json",
        {
            "schema": 0,
            "algorithm": "sha256",
            "object_count": len(inventory_objects),
            "total_bytes": sum(item["bytes"] for item in inventory_objects),
            "objects": inventory_objects,
        },
    )
    _canonical_json(root / "INDEX.json", {"schema": 0, "objects": object_specs})

    game_digest = "sha256:" + hashlib.sha256(b"fixture-game\n").hexdigest()
    capsule_dir = root / "02_CAPSULES" / CAPSULE_ID
    capsule_dir.mkdir(parents=True)
    capsule = capsule_dir / "capsule.json"
    _canonical_json(
        capsule,
        {
            "schema": 0,
            "capsule_id": CAPSULE_ID,
            "game": {
                "title": "Test game",
                "preserved_version": "1.0",
            },
            "objects": [
                {
                    "id": baseline["id"],
                    "digest": baseline["digest"],
                    "archive_path": baseline["archive_path"],
                    "format": baseline["format"],
                    "size": baseline["size"],
                    "roles": ["game", "prefix", "prefix_baseline"],
                    "required": True,
                    "shared": False,
                },
                {
                    "id": ge["id"],
                    "digest": ge["digest"],
                    "archive_path": ge["archive_path"],
                    "format": ge["format"],
                    "size": ge["size"],
                    "roles": ["runner"],
                    "required": True,
                    "shared": True,
                },
            ],
            "persistent_state": [
                {
                    "id": "save",
                    "path": "drive_c/save.dat",
                    "kind": "save",
                    "backup": True,
                    "sensitive": True,
                    "required": False,
                }
            ],
            "profiles": [
                {
                    "id": "linux-base-only",
                    "platform": "linux",
                    "adapter": "wine",
                    "status": "not_tested",
                    "dependencies": [baseline["id"]],
                },
                {
                    "id": "windows-base",
                    "platform": "windows",
                    "adapter": "windows",
                    "status": "candidate",
                    "dependencies": [baseline["id"]],
                },
                {
                    "id": BOTTLES_PROFILE_ID,
                    "platform": "linux",
                    "adapter": "bottles",
                    "status": "verified",
                    "dependencies": [baseline["id"], ge["id"]],
                    "host_contract": "host-contracts/linux-bottles-flatpak.json",
                    "launch": {
                        "entrypoint": "drive_c/Games/Test/game.exe",
                        "working_directory": "drive_c/Games/Test",
                        "arguments": [],
                        "environment": {},
                        "network": "isolated",
                    },
                },
                {
                    "id": PROFILE_ID,
                    "platform": "linux",
                    "adapter": "wine",
                    "status": "verified",
                    "dependencies": [baseline["id"], ge["id"]],
                    "acceptance_report": "acceptance.json",
                    "host_contract": "host-contracts/linux-direct-wine.json",
                    "launch": {
                        "entrypoint": "prefix/drive_c/Games/Test/game.exe",
                        "working_directory": "prefix/drive_c/Games/Test",
                        "arguments": [],
                        "environment": {"WINEDEBUG": "-all"},
                        "network": "host_default",
                    },
                    "playable": {
                        "schema": 0,
                        "backend": "wine",
                        "layout": [
                            {
                                "object": baseline["id"],
                                "source": baseline["source_root"],
                                "destination": "prefix",
                            },
                            {
                                "object": ge["id"],
                                "source": ge["source_root"],
                                "destination": f"runner/{ge['id']}",
                            },
                        ],
                        "paths": {
                            "prefix": "prefix",
                            "runner": f"runner/{ge['id']}",
                            "wine": f"runner/{ge['id']}/files/bin/wine",
                            "wineserver": (
                                f"runner/{ge['id']}/files/bin/wineserver"
                            ),
                            "runtime": "runtime",
                            "launcher": f"play_{CAPSULE_ID}.sh",
                            "uninstaller": f"uninstall_{CAPSULE_ID}.sh",
                        },
                        "prefix_operations": [],
                        "protected_files": [
                            {
                                "path": "prefix/drive_c/Games/Test/game.exe",
                                "digest": game_digest,
                                "size": len(b"fixture-game\n"),
                            }
                        ],
                    },
                },
            ],
        },
    )

    _canonical_json(
        capsule_dir / "host-contracts/linux-direct-wine.json",
        {
            "schema": 0,
            "platform": "linux",
            "adapter": "wine",
            "notes": "fixture host contract",
        },
    )
    _canonical_json(
        capsule_dir / "host-contracts/linux-bottles-flatpak.json",
        {
            "schema": 0,
            "platform": "linux",
            "adapter": "bottles",
            "notes": "fixture Bottles host contract",
        },
    )

    state_declaration = {
        "id": "save",
        "path": "drive_c/save.dat",
        "kind": "save",
        "backup": True,
        "sensitive": True,
        "required": False,
    }
    state_definition_digest = _compact_digest(
        {
            "capsule_id": CAPSULE_ID,
            "persistent_state": [state_declaration],
        }
    )

    accepted = root / "03_PERSISTENT_STATE" / CAPSULE_ID / "accepted"
    (accepted / "payload").mkdir(parents=True)
    _canonical_json(
        accepted / "state-backup.json",
        {
            "schema": 0,
            "backup_id": "accepted-test",
            "capsule_id": CAPSULE_ID,
            "state_definition_digest": state_definition_digest,
            "created_at": "2026-07-23T00:00:00+00:00",
            "orchestrator_version": "0.9.0",
            "backup_kind": "preserved",
            "stopped_confirmed": True,
            "complete": True,
            "items": [
                {
                    "id": "save",
                    "declared_path": "drive_c/save.dat",
                    "kind": "save",
                    "sensitive": True,
                    "required": False,
                    "present": False,
                    "entry_type": "missing",
                    "payload_path": None,
                    "file_count": 0,
                    "directory_count": 0,
                    "bytes": 0,
                    "tree_digest": None,
                    "entries": [],
                }
            ],
        },
    )

    save_payload = b"selected-save\n"
    save_digest = hashlib.sha256(save_payload).hexdigest()
    save_root = (
        root
        / "03_PERSISTENT_STATE"
        / CAPSULE_ID
        / "save-sets"
    )
    save_set_id = "fixture-save"
    save_set_dir = save_root / save_set_id
    save_set_dir.mkdir(parents=True)
    (save_set_dir / "save.dat").write_bytes(save_payload)
    save_manifest = {
        "schema": 0,
        "status": "verified",
        "capsule_id": CAPSULE_ID,
        "save_set_id": save_set_id,
        "display_name": "Test save set",
        "captured_at": "2026-07-23T00:00:00+00:00",
        "captured_at_basis": "fixture",
        "source": {"type": "fixture"},
        "save_definition_digest": _compact_digest(
            state_declaration
        ),
        "items": [
            {
                "kind": "save",
                "state_id": "save",
                "declared_path": "drive_c/save.dat",
                "payload_path": "save.dat",
                "digest": "sha256:" + save_digest,
                "bytes": len(save_payload),
            }
        ],
    }
    _canonical_json(
        save_set_dir / "save-set.json",
        save_manifest,
    )
    save_manifest_sha = hashlib.sha256(
        (save_set_dir / "save-set.json").read_bytes()
    ).hexdigest()
    _canonical_json(
        save_root / "index.json",
        {
            "schema": 0,
            "capsule_id": CAPSULE_ID,
            "selection_policy": "explicit-only",
            "default_save_set_id": None,
            "status": "verified",
            "save_set_count": 1,
            "entries": [
                {
                    "save_set_id": save_set_id,
                    "display_name": "Test save set",
                    "captured_at": "2026-07-23T00:00:00+00:00",
                    "captured_at_basis": "fixture",
                    "source": {"type": "fixture"},
                    "state_id": "save",
                    "digest": "sha256:" + save_digest,
                    "bytes": len(save_payload),
                    "manifest": f"{save_set_id}/save-set.json",
                    "manifest_sha256": save_manifest_sha,
                    "status": "verified",
                }
            ],
        },
    )
    _canonical_json(
        root
        / "03_PERSISTENT_STATE"
        / "SAVE_LIBRARY_CONTRACT.json",
        {
            "schema": 0,
            "contract": "ogv-save-library-v1",
            "default_selection": "none",
            "selection_policy": "explicit-only",
            "status": "verified",
        },
    )

    receipt_root = (
        root
        / "04_RECEIPTS/_collection/operations"
        / "add-shared-runner-soda-test"
    )
    receipt_root.mkdir(parents=True)
    _canonical_json(
        receipt_root / "receipt.json",
        {
            "schema": 0,
            "operation": "add-shared-runner",
            "runner": {"id": SODA_RUNNER_ID},
            "archive": {
                "digest": soda["digest"],
                "format": soda["format"],
                "top_level": soda["source_root"],
            },
        },
    )
    _canonical_json(
        receipt_root / "source-tree.json",
        {
            "schema": 0,
            "runner_id": SODA_RUNNER_ID,
            "entries": [
                {"path": "bin/wine", "type": "file"},
                {"path": "bin/wineserver", "type": "file"},
            ],
        },
    )

    backend_receipt_root = (
        root
        / "04_RECEIPTS/_collection/operations"
        / "add-shared-backend-bottles-test"
    )
    backend_receipt_root.mkdir(parents=True)
    _canonical_json(
        backend_receipt_root / "receipt.json",
        {
            "schema": 0,
            "operation": "add-shared-backend",
            "archive": {
                "digest": f"sha256:{backend_digest}",
                "bytes": len(backend_payload),
                "format": "tar.zst",
                "path": backend_relative,
            },
            "backend": {
                "id": "bottles-flatpak-64.1-x86_64-stable",
                "classification": "shared-backend",
                "application_ref": BOTTLES_APP_REF,
                "application_commit": BOTTLES_APP_COMMIT,
                "version": "64.1",
            },
        },
    )

    (root / "COLLECTION_LAYOUT.json").write_text("{}\n", encoding="utf-8")
    (root / "COLLECTION_SHA256.txt").write_text("fixture\n", encoding="utf-8")
    return root, capsule


def runners_by_id(root: Path) -> dict[str, RunnerRecord]:
    runners, warnings = scan_runners(root)
    assert not warnings, warnings
    return {runner.runner_id: runner for runner in runners}



def save_sets(root: Path, capsule: Path):
    records, warnings = scan_save_sets(
        root,
        capsule_path=capsule,
        capsule_id=CAPSULE_ID,
    )
    assert not warnings, warnings
    return records

def bottles_backend(root: Path):
    return scan_shared_bottles_backend(root)


def create_playable_destination(
    destination: Path,
    runner: RunnerRecord,
    *,
    capsule_id: str = CAPSULE_ID,
    profile_id: str = PROFILE_ID,
) -> None:
    destination.mkdir()
    launcher = destination / f"play_{capsule_id}.sh"
    uninstaller = destination / f"uninstall_{capsule_id}.sh"
    for script in (launcher, uninstaller):
        script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        script.chmod(0o700)

    _canonical_json(
        destination / "playable-materialization.json",
        {
            "schema": 0,
            "complete": True,
            "capsule_id": capsule_id,
            "profile_id": profile_id,
            "backend": "wine",
            "destination": ".",
            "objects": [
                {
                    "id": runner.runner_id,
                    "digest": runner.digest,
                    "destination": f"objects/{runner.runner_id}",
                    "strategy": "extract",
                    "verified": True,
                }
            ],
            "layout": [
                {
                    "object": runner.runner_id,
                    "source": runner.source_root,
                    "destination": f"runner/{runner.runner_id}",
                }
            ],
            "paths": {
                "runner": f"runner/{runner.runner_id}",
                "wine": (
                    f"runner/{runner.runner_id}/{runner.wine_path}"
                ),
                "wineserver": (
                    f"runner/{runner.runner_id}/{runner.wineserver_path}"
                ),
                "launcher": launcher.name,
                "uninstaller": uninstaller.name,
            },
        },
    )


def create_base_destination(
    destination: Path,
    *,
    profile_id: str = BOTTLES_PROFILE_ID,
) -> Path:
    """Create a recognized base materialization for the fixture capsule."""

    bottle = destination / "objects/baseline/Game"
    (bottle / "drive_c/Games/Test").mkdir(parents=True)
    (bottle / "drive_c/Games/Test/game.exe").write_bytes(b"fixture-game\n")
    (bottle / "drive_c/Games/Test/game.exe").chmod(0o755)
    (bottle / "drive_c/save.dat").write_bytes(b"save\n")
    (bottle / "bottle.yml").write_text(
        'Name: "Game"\n'
        'Path: "Game"\n'
        'Custom_Path: false\n'
        f'Runner: "{GE_RUNNER_ID}"\n',
        encoding="utf-8",
    )
    _canonical_json(
        destination / "materialization-receipt.json",
        {
            "schema": 0,
            "receipt_id": "base-test",
            "capsule_id": CAPSULE_ID,
            "profile_id": profile_id,
            "destination": ".",
            "complete": True,
            "objects": [
                {
                    "id": "baseline",
                    "destination": "objects/baseline",
                    "strategy": "extract",
                    "verified": True,
                }
            ],
        },
    )
    return bottle


def create_bottles_deployment(
    bottles_path: Path,
    *,
    bottle_name: str,
    runner_id: str,
    profile_id: str = BOTTLES_PROFILE_ID,
) -> Path:
    deployment = bottles_path / bottle_name
    (deployment / "drive_c/Games/Test").mkdir(parents=True)
    (deployment / "drive_c/Games/Test/game.exe").write_bytes(b"fixture-game\n")
    (deployment / "drive_c/Games/Test/game.exe").chmod(0o755)
    (deployment / "bottle.yml").write_text(
        f'Name: "{bottle_name}"\n'
        f'Path: "{bottle_name}"\n'
        'Custom_Path: false\n'
        f'Runner: "{runner_id}"\n',
        encoding="utf-8",
    )
    _canonical_json(
        deployment / ".ogv-bottles-deployment.json",
        {
            "schema": 0,
            "adapter": "bottles-flatpak",
            "deployment_id": "deployment-test",
            "capsule_id": CAPSULE_ID,
            "profile_id": profile_id,
            "source_object_id": "baseline",
            "bottle_name": bottle_name,
            "destination": ".",
            "runner": runner_id,
            "launch": {
                "entrypoint": "drive_c/Games/Test/game.exe",
                "arguments": [],
                "network": "isolated",
            },
            "persistent_state": [],
        },
    )
    return deployment
