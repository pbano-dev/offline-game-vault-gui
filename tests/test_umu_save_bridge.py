from __future__ import annotations

import hashlib
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from offline_game_vault_gui.model import (
    SaveSetItemRecord,
    SaveSetRecord,
)
from offline_game_vault_gui.save_sets import scan_save_sets
from offline_game_vault_gui.umu_model import (
    UmuBackendTemplate,
    UmuProfile,
    UmuSelection,
)
from offline_game_vault_gui.umu_state_bridge import (
    prepare_derived_state,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


class UmuSaveSetBridgeTests(unittest.TestCase):
    def test_scanner_resolves_payload_relative_to_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            collection = Path(temporary)
            root = (
                collection
                / "03_PERSISTENT_STATE"
                / "steam-test"
                / "save-sets"
            )
            payload = root / "2025-04-25/payload/0000-save/data"
            payload.parent.mkdir(parents=True)
            payload.write_bytes(b"save-data")
            manifest = root / "2025-04-25/save-set.json"
            _write_json(
                manifest,
                {
                    "items": [
                        {
                            "state_id": "main-save",
                            "declared_path": "drive_c/save.bin",
                            "digest": f"sha256:{_sha256(payload)}",
                            "bytes": payload.stat().st_size,
                            "entry_type": "file",
                            "payload_path":
                                "payload/0000-save/data",
                        }
                    ]
                },
            )
            _write_json(
                root / "index.json",
                {
                    "entries": [
                        {
                            "save_set_id": "2025-04-25",
                            "display_name": "25 April 2025",
                            "manifest": "2025-04-25/save-set.json",
                            "manifest_sha256": _sha256(manifest),
                            "bytes": payload.stat().st_size,
                            "digest": f"sha256:{_sha256(payload)}",
                            "status": "verified",
                        }
                    ]
                },
            )

            records, warnings = scan_save_sets(
                collection,
                "steam-test",
            )

            self.assertEqual(warnings, ())
            self.assertEqual(len(records), 1)
            self.assertEqual(
                records[0].items[0].payload_path,
                payload,
            )
            self.assertEqual(
                records[0].items[0].entry_type,
                "file",
            )

    def test_selected_save_is_bridged_and_identity_is_verified(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            save_payload = root / "save/data"
            save_payload.parent.mkdir(parents=True)
            save_payload.write_bytes(b"accepted-save")
            save_manifest = root / "save/save-set.json"
            _write_json(save_manifest, {"schema": 0})

            accepted = root / "accepted"
            identity = accepted / "payload/0001-identity/data"
            identity.parent.mkdir(parents=True)
            identity.write_bytes(b"identity=123\n")
            identity_digest = _sha256(identity)
            _write_json(
                accepted / "state-backup.json",
                {
                    "items": [
                        {
                            "id": "gbe-user-identity",
                            "kind": "identity",
                            "present": True,
                            "entry_type": "file",
                            "declared_path": (
                                "drive_c/users/steamuser/AppData/"
                                "Roaming/GSE Saves/settings/"
                                "configs.user.ini"
                            ),
                            "payload_path":
                                "payload/0001-identity/data",
                            "entries": [
                                {
                                    "path": ".",
                                    "type": "file",
                                    "bytes": identity.stat().st_size,
                                    "digest":
                                        f"sha256:{identity_digest}",
                                }
                            ],
                        }
                    ]
                },
            )

            save_record = SaveSetRecord(
                capsule_id="steam-test",
                save_set_id="2025-04-25",
                display_name="25 April 2025",
                captured_at="2025-04-25",
                captured_at_basis="test",
                aggregate_digest=_sha256(save_payload),
                size=save_payload.stat().st_size,
                manifest_path=save_manifest,
                manifest_digest=_sha256(save_manifest),
                items=(
                    SaveSetItemRecord(
                        state_id="main-save",
                        declared_path=(
                            "drive_c/users/steamuser/Documents/"
                            "GAME/save.bin"
                        ),
                        digest=_sha256(save_payload),
                        size=save_payload.stat().st_size,
                        payload_path=save_payload,
                        entry_type="file",
                    ),
                ),
                status="verified",
                source=None,
            )

            capsule = {
                "capsule_id": "steam-test",
                "persistent_state": [
                    {
                        "id": "main-save",
                        "kind": "save",
                        "required": False,
                    },
                    {
                        "id": "gbe-user-identity",
                        "kind": "identity",
                        "required": True,
                    },
                ],
            }
            source_profile = {
                "playable": {
                    "paths": {
                        "prefix": "prefix",
                    }
                }
            }
            template = UmuBackendTemplate(
                capsule_path=root / "capsule.json",
                capsule={},
                profile_id="template",
                composite_object_id="stack",
                composite_digest="1" * 64,
                composite_object={},
                source_mapping={},
                runtime_var="engine/xdg-data/umu/runtime/var",
            )
            profile = UmuProfile(
                capsule_id="steam-test",
                title="Test",
                preserved_version="1",
                capsule_path=root / "capsule.json",
                profile_id="wine-umu-candidate",
                profile_status="candidate",
                kind="derived-wine",
                source_profile_id="wine",
                state_root=None,
                state_archives=(),
                original_profile=source_profile,
                capsule=capsule,
                backend_template=template,
                save_sets=(save_record,),
                accepted_state_root=accepted,
            )
            selection = UmuSelection(
                collection_root=root,
                immutable_vault_root=root,
                profile=profile,
                runner=None,
                destination=root / "destination",
                save_id=save_record.save_set_id,
                save_set=save_record,
            )

            overlay = root / "overlay"
            overlay.mkdir()
            prepared = prepare_derived_state(
                selection,
                overlay,
            )

            self.assertEqual(
                prepared.selected_save_id,
                "2025-04-25",
            )
            self.assertEqual(len(prepared.state_archives), 1)
            archive = (
                prepared.state_root
                / prepared.state_archives[0]["filename"]
            )
            with tarfile.open(archive, "r") as handle:
                names = {
                    member.name
                    for member in handle.getmembers()
                    if member.isfile()
                }
            save_destination = (
                "prefix/drive_c/users/steamuser/Documents/"
                "GAME/save.bin"
            )
            identity_destination = (
                "prefix/drive_c/users/steamuser/AppData/"
                "Roaming/GSE Saves/settings/configs.user.ini"
            )
            self.assertEqual(names, {save_destination})
            self.assertEqual(
                prepared.mutable_paths,
                (save_destination,),
            )
            required_manifest = (
                overlay / "manifests/required-state.sha256"
            ).read_text(encoding="utf-8")
            self.assertIn(identity_digest, required_manifest)
            self.assertIn(identity_destination, required_manifest)
            save_protected = (
                overlay
                / "manifests/save-2025-04-25.sha256"
            ).read_text(encoding="utf-8")
            self.assertIn(_sha256(save_payload), save_protected)
            self.assertIn(save_destination, save_protected)


if __name__ == "__main__":
    unittest.main()
