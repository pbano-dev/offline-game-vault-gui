from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from offline_game_vault_gui.model import (
    RunnerRecord,
    SaveSetItemRecord,
    SaveSetRecord,
    ValidatedRequest,
)
from offline_game_vault_gui.neutral_profiles import (
    NeutralProfileError,
    materialize_neutral_bottle_source,
    validate_neutral_bottles_source,
)
from offline_game_vault_gui.bottles_backend import (
    find_materialized_bottle_yml,
    temporary_runner_override,
)
from offline_game_vault_gui.runner_override import build_derived_capsule
from offline_game_vault_gui.save_sets import scan_save_sets
from offline_game_vault_gui.state_selection import prepared_state_backup
from offline_game_vault_gui.windows_export import (
    transform_base_to_windows_export,
)


CAPSULE_ID = "steam-999-imported-1.0"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def runner() -> RunnerRecord:
    return RunnerRecord(
        runner_id="proton9",
        digest="sha256:" + "a" * 64,
        archive_path="objects/sha256/aa/aa/" + "a" * 64,
        size=123,
        format="tar.gz",
        source_root="proton9",
        wine_path="files/bin/wine",
        wineserver_path="files/bin/wineserver",
        compatible_backends=("direct-wine", "bottles"),
        metadata_source="fixture",
    )


def capsule(
    root: Path,
    *,
    profile_id: str,
    adapter: str,
    contract: str,
) -> Path:
    capsule_dir = root / "02_CAPSULES" / CAPSULE_ID
    capsule_dir.mkdir(parents=True)
    host_name = {
        "wine": "linux-direct-wine.json",
        "bottles": "linux-bottles.json",
        "windows": "windows-native.json",
    }[adapter]
    host_path = capsule_dir / "host-contracts" / host_name
    host = {
        "schema": 0,
        "contract": contract,
        "source_object": "game-baseline",
        "neutral_root": "neutral-object",
        "prefix_source": "neutral-object/payload/prefix-template",
        "game_source": "neutral-object/payload/game",
        "game_destination_in_prefix": "drive_c/Games/Imported",
        "entrypoint_relative_to_game": "Imported.exe",
        "working_directory_in_prefix": "drive_c/Games/Imported",
        "baseline_state": "clean",
        "runner_binding": "select-at-materialization",
        "preferred_runner": None,
    }
    if adapter == "wine":
        host.update({
            "runtime_directory": "runtime",
            "launcher": "PLAY.sh",
            "uninstaller": "REMOVE.sh",
            "protected_files": [{
                "path": "prefix/drive_c/Games/Imported/Imported.exe",
                "digest": "sha256:" + hashlib.sha256(b"game").hexdigest(),
                "size": 4,
            }],
            "network": "host_default",
        })
    elif adapter == "bottles":
        host.update({
            "bottle_yml_template": "evidence/source-bottles/bottle.yml",
            "network": "isolated",
        })
    elif adapter == "windows":
        host.update({
            "game_destination": "game",
            "state_destination_policy": "powershell-profile-map",
        })
    write_json(host_path, host)
    capsule_path = capsule_dir / "capsule.json"
    write_json(capsule_path, {
        "schema": 0,
        "capsule_id": CAPSULE_ID,
        "game": {
            "title": "Imported",
            "source_store": "Steam",
            "preserved_version": "1.0",
        },
        "documents": {
            "readme": "docs/00_README.md",
            "game_sheet": "docs/GAME_SHEET.md",
            "credits": "docs/CREDITOS.md",
            "preserved_by": "docs/PRESERVED_BY.md",
        },
        "objects": [{
            "id": "game-baseline",
            "digest": "sha256:" + "b" * 64,
            "roles": ["game_payload", "prefix_baseline"],
            "format": "tar.gz",
            "required": True,
            "archive_path": "objects/sha256/bb/bb/" + "b" * 64,
            "shared": False,
        }],
        "persistent_state": [],
        "profiles": [{
            "id": profile_id,
            "platform": "windows" if adapter == "windows" else "linux",
            "adapter": adapter,
            "status": "candidate" if adapter != "windows" else "not_tested",
            "dependencies": ["game-baseline"],
            "host_contract": f"host-contracts/{host_name}",
            "launch": {
                "entrypoint": (
                    "game/Imported.exe"
                    if adapter == "windows"
                    else "drive_c/Games/Imported/Imported.exe"
                ),
                "working_directory": (
                    "game"
                    if adapter == "windows"
                    else "drive_c/Games/Imported"
                ),
                "arguments": [],
                "network": "host_default",
            },
        }],
    })
    return capsule_path


class ImportedCandidateTests(unittest.TestCase):
    def test_unbound_direct_wine_becomes_playable_with_selected_runner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capsule_path = capsule(
                root,
                profile_id="linux-direct-wine",
                adapter="wine",
                contract="ogv-direct-wine-neutral-v1",
            )
            derived = build_derived_capsule(
                capsule_path, "linux-direct-wine", runner()
            )
            profile = derived.document["profiles"][0]
            self.assertTrue(derived.changed)
            self.assertEqual(profile["status"], "not_tested")
            self.assertEqual(profile["playable"]["backend"], "wine")
            self.assertEqual(
                [item["destination"] for item in profile["playable"]["layout"]],
                [
                    "source",
                    "runner/proton9",
                ],
            )
            self.assertEqual(
                [item["source"] for item in profile["playable"]["layout"]],
                [
                    "neutral-object",
                    "proton9",
                ],
            )
            self.assertEqual(
                profile["playable"]["paths"]["prefix"],
                "source/payload/prefix-template",
            )
            self.assertEqual(
                profile["playable"]["prefix_operations"],
                [{
                    "type": "symlink",
                    "path": (
                        "source/payload/prefix-template/"
                        "drive_c/Games/Imported"
                    ),
                    "target": "../../../game",
                }],
            )
            self.assertIn("proton9", profile["dependencies"])
            self.assertEqual(
                len({
                    item["object"]
                    for item in profile["playable"]["layout"]
                }),
                len(profile["playable"]["layout"]),
            )

    def test_neutral_bottles_source_preserves_materialization_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capsule_path = capsule(
                root,
                profile_id="linux-bottles-flatpak",
                adapter="bottles",
                contract="ogv-bottles-neutral-v1",
            )
            template = (
                capsule_path.parent
                / "evidence/source-bottles/bottle.yml"
            )
            template.parent.mkdir(parents=True)
            template.write_text(
                "Name: Imported-old\n"
                "Path: /home/example-user/Imported-old\n"
                "Runner: old-runner\n"
                "Custom_Path: /home/example-user/Bottles\n"
                "Runner: duplicate-runner\n",
                encoding="utf-8",
            )

            materialization = root / "materialization"
            object_root = materialization / "objects/game-baseline"
            prefix = (
                object_root
                / "neutral-object/payload/prefix-template"
            )
            game = (
                object_root
                / "neutral-object/payload/game"
            )
            (prefix / "drive_c/users/steamuser").mkdir(
                parents=True
            )
            game.mkdir(parents=True)
            (game / "Imported.exe").write_bytes(b"game")
            runner_root = materialization / "objects/proton9"
            runner_root.mkdir(parents=True)
            (runner_root / "runner-marker").write_bytes(b"runner")

            materialization_receipt = {
                "schema": 0,
                "receipt_id": "materialization-fixture",
                "capsule_id": CAPSULE_ID,
                "profile_id": "linux-bottles-flatpak",
                "destination": ".",
                "objects": [
                    {
                        "id": "game-baseline",
                        "destination": "objects/game-baseline",
                        "strategy": "extract",
                        "verified": True,
                    },
                    {
                        "id": "proton9",
                        "destination": "objects/proton9",
                        "strategy": "extract",
                        "verified": True,
                    },
                ],
                "removal": {
                    "safe_to_remove": [
                        "objects",
                        "materialization-receipt.json",
                    ],
                },
            }
            write_json(
                materialization / "materialization-receipt.json",
                materialization_receipt,
            )
            before_receipt = (
                materialization / "materialization-receipt.json"
            ).read_bytes()

            receipt = materialize_neutral_bottle_source(
                materialization=materialization,
                capsule_path=capsule_path,
                profile_id="linux-bottles-flatpak",
                runner=runner(),
                bottle_name="Imported",
            )
            self.assertIsNotNone(receipt)
            self.assertTrue(receipt["object_scoped"])

            bottle_root = materialization / "objects/game-baseline"
            self.assertTrue(
                (
                    bottle_root
                    / "drive_c/Games/Imported/Imported.exe"
                ).is_file()
            )
            bottle_yml_path = bottle_root / "bottle.yml"
            bottle_yml = bottle_yml_path.read_text()
            self.assertEqual(
                sum(
                    1 for line in bottle_yml.splitlines()
                    if line.startswith("Runner:")
                ),
                1,
            )
            self.assertIn("Runner: proton9", bottle_yml)
            self.assertIn('Name: "Imported"', bottle_yml)
            self.assertIn('Path: "Imported"', bottle_yml)
            self.assertIn("Custom_Path: false", bottle_yml)
            self.assertNotIn("/home/", bottle_yml)

            self.assertFalse(
                (bottle_root / "neutral-object").exists()
            )
            self.assertTrue(
                (runner_root / "runner-marker").is_file()
            )
            self.assertEqual(
                (
                    materialization / "materialization-receipt.json"
                ).read_bytes(),
                before_receipt,
            )
            self.assertEqual(
                {path.name for path in materialization.iterdir()},
                {"objects", "materialization-receipt.json"},
            )
            self.assertEqual(
                find_materialized_bottle_yml(materialization),
                bottle_yml_path,
            )
            preflight = validate_neutral_bottles_source(
                materialization=materialization,
                capsule_path=capsule_path,
                profile_id="linux-bottles-flatpak",
            )
            self.assertTrue(preflight["wrapper_preserved"])
            self.assertEqual(
                preflight["object_root"],
                "objects/game-baseline",
            )

            # Mirror the core deploy-bottles preconditions that previously
            # failed after the GUI replaced the wrapper itself.
            parsed = json.loads(before_receipt)
            matches = [
                item
                for item in parsed["objects"]
                if item["id"] == "game-baseline"
            ]
            self.assertEqual(len(matches), 1)
            self.assertEqual(
                matches[0]["destination"],
                "objects/game-baseline",
            )
            self.assertTrue(
                (
                    materialization
                    / matches[0]["destination"]
                ).is_dir()
            )

            # A retry is idempotent and does not rebuild or erase the wrapper.
            retried = materialize_neutral_bottle_source(
                materialization=materialization,
                capsule_path=capsule_path,
                profile_id="linux-bottles-flatpak",
                runner=runner(),
                bottle_name="Imported",
            )
            self.assertTrue(retried["reused"])
            self.assertTrue(
                (runner_root / "runner-marker").is_file()
            )

            with temporary_runner_override(
                materialization,
                selected_runner="proton9-alt",
                runner_digest="sha256:" + "e" * 64,
                gui_version="test",
            ) as (selected_yml, original, changed):
                self.assertEqual(selected_yml, bottle_yml_path)
                self.assertEqual(original, "proton9")
                self.assertTrue(changed)
                self.assertIn(
                    'Runner: "proton9-alt"',
                    bottle_yml_path.read_text(),
                )
            self.assertIn(
                "Runner: proton9",
                bottle_yml_path.read_text(),
            )

    def test_neutral_bottles_direct_root_fixture_remains_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capsule_path = capsule(
                root,
                profile_id="linux-bottles-flatpak",
                adapter="bottles",
                contract="ogv-bottles-neutral-v1",
            )
            # Remove source_object to exercise the legacy direct-root fallback.
            host_path = (
                capsule_path.parent
                / "host-contracts/linux-bottles.json"
            )
            host = json.loads(host_path.read_text(encoding="utf-8"))
            host.pop("source_object", None)
            write_json(host_path, host)

            materialization = root / "materialization"
            prefix = (
                materialization
                / "neutral-object/payload/prefix-template"
            )
            game = (
                materialization
                / "neutral-object/payload/game"
            )
            (prefix / "drive_c/users/steamuser").mkdir(
                parents=True
            )
            game.mkdir(parents=True)
            (game / "Imported.exe").write_bytes(b"game")

            receipt = materialize_neutral_bottle_source(
                materialization=materialization,
                capsule_path=capsule_path,
                profile_id="linux-bottles-flatpak",
                runner=runner(),
                bottle_name="Imported",
            )
            self.assertFalse(receipt["object_scoped"])
            self.assertTrue(
                (
                    materialization
                    / "drive_c/Games/Imported/Imported.exe"
                ).is_file()
            )
            self.assertTrue(
                (materialization / "bottle.yml").is_file()
            )
            self.assertFalse(
                (materialization / "neutral-object").exists()
            )
            with self.assertRaises(NeutralProfileError):
                validate_neutral_bottles_source(
                    materialization=materialization,
                    capsule_path=capsule_path,
                    profile_id="linux-bottles-flatpak",
                )

    def test_windows_export_uses_multi_item_save_without_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capsule_path = capsule(
                root,
                profile_id="windows-native",
                adapter="windows",
                contract="ogv-windows-export-v1",
            )
            materialization = root / "materialization"
            game = materialization / "objects/game-baseline/neutral-object/payload/game"
            game.mkdir(parents=True)
            (game / "Imported.exe").write_bytes(b"game")
            save_a = root / "save.sl2"
            save_b = root / "save.sl2.bak"
            save_a.write_bytes(b"save")
            save_b.write_bytes(b"backup")
            items = (
                SaveSetItemRecord(
                    state_id="main",
                    declared_path=(
                        "drive_c/users/steamuser/AppData/Roaming/"
                        "Imported/save.sl2"
                    ),
                    digest="sha256:" + hashlib.sha256(b"save").hexdigest(),
                    size=4,
                    payload_path=save_a,
                ),
                SaveSetItemRecord(
                    state_id="backup",
                    declared_path=(
                        "drive_c/users/steamuser/AppData/Roaming/"
                        "Imported/save.sl2.bak"
                    ),
                    digest="sha256:" + hashlib.sha256(b"backup").hexdigest(),
                    size=6,
                    payload_path=save_b,
                ),
            )
            save_set = SaveSetRecord(
                capsule_id=CAPSULE_ID,
                save_set_id="principal",
                display_name="Principal",
                captured_at="2026-07-24",
                captured_at_basis="fixture",
                aggregate_digest="sha256:" + "c" * 64,
                size=10,
                manifest_path=root / "save-set.json",
                manifest_digest="sha256:" + "d" * 64,
                items=items,
                status="candidate",
                source={"type": "fixture"},
            )
            receipt = transform_base_to_windows_export(
                materialization=materialization,
                capsule_path=capsule_path,
                profile_id="windows-native",
                capsule_id=CAPSULE_ID,
                save_set=save_set,
            )
            self.assertEqual(receipt["state_item_count"], 2)
            self.assertTrue((materialization / "game/Imported.exe").is_file())
            self.assertTrue((materialization / "PLAY.cmd").is_file())
            self.assertTrue((materialization / "INSTALL_STATE.ps1").is_file())
            self.assertFalse((materialization / "neutral-object").exists())
            self.assertFalse((materialization / "prefix").exists())
            state_map = json.loads(
                (materialization / "STATE_MAP.json").read_text()
            )
            self.assertEqual(len(state_map["items"]), 2)
            self.assertTrue(
                state_map["items"][0]["windows_destination"].startswith(
                    "%APPDATA%\\"
                )
            )


    def test_windows_export_uses_composed_state_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capsule_path = capsule(
                root,
                profile_id="windows-native",
                adapter="windows",
                contract="ogv-windows-export-v1",
            )
            materialization = root / "materialization"
            game = materialization / "objects/game-baseline/neutral-object/payload/game"
            game.mkdir(parents=True)
            (game / "Imported.exe").write_bytes(b"game")

            backup = root / "composed-state"
            payload = backup / "payload"
            (payload / "0000-config").mkdir(parents=True)
            (payload / "0000-config/data").write_bytes(b"config")
            (payload / "0001-main").mkdir(parents=True)
            (payload / "0001-main/data").write_bytes(b"save")
            write_json(backup / "state-backup.json", {
                "schema": 0,
                "capsule_id": CAPSULE_ID,
                "complete": True,
                "items": [
                    {
                        "id": "config",
                        "declared_path": (
                            "drive_c/users/steamuser/AppData/Roaming/"
                            "Imported/GraphicsConfig.xml"
                        ),
                        "kind": "configuration",
                        "present": True,
                        "entry_type": "file",
                        "payload_path": "payload/0000-config/data",
                        "bytes": 6,
                        "tree_digest": "sha256:" + "1" * 64,
                    },
                    {
                        "id": "main",
                        "declared_path": (
                            "drive_c/users/steamuser/AppData/Roaming/"
                            "Imported/save.sl2"
                        ),
                        "kind": "save",
                        "present": True,
                        "entry_type": "file",
                        "payload_path": "payload/0001-main/data",
                        "bytes": 4,
                        "tree_digest": "sha256:" + "2" * 64,
                    },
                    {
                        "id": "absent",
                        "declared_path": (
                            "drive_c/users/steamuser/AppData/Roaming/"
                            "Imported/absent.dat"
                        ),
                        "kind": "other",
                        "present": False,
                        "entry_type": "missing",
                    },
                ],
            })

            receipt = transform_base_to_windows_export(
                materialization=materialization,
                capsule_path=capsule_path,
                profile_id="windows-native",
                capsule_id=CAPSULE_ID,
                save_set=None,
                state_backup=backup,
            )
            self.assertEqual(receipt["state_item_count"], 2)
            state_map = json.loads(
                (materialization / "STATE_MAP.json").read_text()
            )
            self.assertEqual(
                [item["kind"] for item in state_map["items"]],
                ["configuration", "save"],
            )
            self.assertTrue(
                (
                    materialization
                    / "selected-state/0000-config/data"
                ).is_file()
            )
            self.assertTrue(
                (
                    materialization
                    / "selected-state/0001-main/data"
                ).is_file()
            )


    def test_candidate_multifile_save_is_scanned_and_composed_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capsule_dir = root / "02_CAPSULES" / CAPSULE_ID
            capsule_dir.mkdir(parents=True)
            declarations = [
                {
                    "id": "backup",
                    "path": "drive_c/users/steamuser/AppData/Roaming/Imported/save.sl2.bak",
                    "kind": "save",
                    "backup": True,
                    "sensitive": True,
                    "required": False,
                },
                {
                    "id": "main",
                    "path": "drive_c/users/steamuser/AppData/Roaming/Imported/save.sl2",
                    "kind": "save",
                    "backup": True,
                    "sensitive": True,
                    "required": False,
                },
            ]
            capsule_path = capsule_dir / "capsule.json"
            write_json(capsule_path, {
                "schema": 0,
                "capsule_id": CAPSULE_ID,
                "game": {
                    "title": "Imported",
                    "source_store": "Steam",
                    "preserved_version": "1.0",
                },
                "documents": {
                    "readme": "docs/00_README.md",
                    "game_sheet": "docs/GAME_SHEET.md",
                    "credits": "docs/CREDITOS.md",
                    "preserved_by": "docs/PRESERVED_BY.md",
                },
                "objects": [{
                    "id": "game-baseline",
                    "digest": "sha256:" + "b" * 64,
                    "roles": ["game_payload"],
                    "format": "tar.gz",
                    "required": True,
                }],
                "persistent_state": declarations,
                "profiles": [],
            })
            accepted = (
                root / "03_PERSISTENT_STATE" / CAPSULE_ID / "accepted"
            )
            (accepted / "payload").mkdir(parents=True)
            write_json(accepted / "state-backup.json", {
                "schema": 0,
                "backup_id": "accepted",
                "capsule_id": CAPSULE_ID,
                "complete": True,
                "items": [
                    {
                        "id": item["id"],
                        "declared_path": item["path"],
                        "kind": "save",
                        "sensitive": True,
                        "required": False,
                        "present": False,
                        "entry_type": "missing",
                    }
                    for item in sorted(declarations, key=lambda item: item["id"])
                ],
            })
            write_json(
                root / "03_PERSISTENT_STATE/SAVE_LIBRARY_CONTRACT.json",
                {
                    "schema": 0,
                    "contract": "ogv-save-library-v2",
                    "default_selection": "none",
                    "selection_policy": "explicit-only",
                },
            )
            save_root = (
                root / "03_PERSISTENT_STATE" / CAPSULE_ID
                / "save-sets/principal"
            )
            payloads = {
                "backup": b"backup",
                "main": b"main",
            }
            manifest_items = []
            definitions = {}
            for index, declaration in enumerate(declarations):
                state_id = declaration["id"]
                payload_path = (
                    save_root / f"payload/{index:04d}-{state_id}/data"
                )
                payload_path.parent.mkdir(parents=True, exist_ok=True)
                payload_path.write_bytes(payloads[state_id])
                digest = "sha256:" + hashlib.sha256(
                    payloads[state_id]
                ).hexdigest()
                manifest_items.append({
                    "state_id": state_id,
                    "kind": "save",
                    "declared_path": declaration["path"],
                    "entry_type": "file",
                    "payload_path": (
                        f"payload/{index:04d}-{state_id}/data"
                    ),
                    "digest": digest,
                    "bytes": len(payloads[state_id]),
                    "file_count": 1,
                    "directory_count": 0,
                })
                normalized = {
                    "id": declaration["id"],
                    "path": declaration["path"],
                    "kind": declaration["kind"],
                    "backup": True,
                    "sensitive": True,
                    "required": False,
                }
                definitions[state_id] = "sha256:" + hashlib.sha256(
                    json.dumps(
                        normalized,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest()
            aggregate = "sha256:" + hashlib.sha256(
                json.dumps(
                    [
                        {
                            "state_id": item["state_id"],
                            "declared_path": item["declared_path"],
                            "digest": item["digest"],
                            "bytes": item["bytes"],
                            "entry_type": item["entry_type"],
                        }
                        for item in manifest_items
                    ],
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            manifest = {
                "schema": 0,
                "contract": "ogv-save-set-v2",
                "status": "candidate",
                "capsule_id": CAPSULE_ID,
                "save_set_id": "principal",
                "display_name": "Principal",
                "captured_at": "2026-07-24",
                "captured_at_basis": "fixture",
                "items": manifest_items,
                "state_ids": [item["state_id"] for item in manifest_items],
                "save_definition_digests": definitions,
                "aggregate_digest": aggregate,
                "total_bytes": sum(item["bytes"] for item in manifest_items),
                "source": {"type": "fixture"},
            }
            write_json(save_root / "save-set.json", manifest)
            manifest_sha = hashlib.sha256(
                (save_root / "save-set.json").read_bytes()
            ).hexdigest()
            write_json(save_root.parent / "index.json", {
                "schema": 0,
                "contract": "ogv-save-library-v2",
                "capsule_id": CAPSULE_ID,
                "selection_policy": "explicit-only",
                "default_save_set_id": None,
                "status": "candidate",
                "save_set_count": 1,
                "entries": [{
                    "save_set_id": "principal",
                    "display_name": "Principal",
                    "captured_at": "2026-07-24",
                    "captured_at_basis": "fixture",
                    "manifest": "principal/save-set.json",
                    "manifest_sha256": manifest_sha,
                    "status": "candidate",
                    "state_ids": [item["state_id"] for item in manifest_items],
                    "item_count": 2,
                    "bytes": sum(item["bytes"] for item in manifest_items),
                    "aggregate_digest": aggregate,
                }],
            })
            records, warnings = scan_save_sets(
                root,
                capsule_path=capsule_path,
                capsule_id=CAPSULE_ID,
            )
            self.assertEqual(warnings, ())
            self.assertEqual(len(records), 1)
            self.assertEqual(len(records[0].items), 2)
            destination = root / "materialized"
            destination.mkdir()
            request = ValidatedRequest(
                collection_root=root,
                immutable_vault_root=root / "01_IMMUTABLE_VAULT",
                capsule_path=capsule_path,
                capsule_id=CAPSULE_ID,
                profile_id="linux-direct-wine",
                backend_id="direct-wine",
                destination_parent=destination,
                destination=destination / "game",
                mode="playable",
                state_backup=accepted,
                save_set=records[0],
                runner=runner(),
                default_runner_id=None,
                overlay_required=True,
                reusable=False,
                source_reusable=False,
                control_reusable=False,
                bottles_path=None,
                bottle_name=None,
                deployment_path=None,
            )
            with prepared_state_backup(request) as prepared:
                receipt = json.loads(
                    (prepared.backup_path / "state-backup.json").read_text()
                )
                self.assertEqual(
                    [item["id"] for item in receipt["items"]],
                    ["backup", "main"],
                )
                self.assertTrue(all(item["present"] for item in receipt["items"]))



if __name__ == "__main__":
    unittest.main()
