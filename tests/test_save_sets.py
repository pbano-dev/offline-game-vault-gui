from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from offline_game_vault_gui.guard import (
    resolve_destination,
    validate_request,
    variant_destination_name,
)
from offline_game_vault_gui.model import MaterializationRequest
from offline_game_vault_gui.save_sets import scan_save_sets
from offline_game_vault_gui.state_selection import prepared_state_backup

from helpers import (
    CAPSULE_ID,
    PROFILE_ID,
    create_collection,
    runners_by_id,
)


class SaveSetTests(unittest.TestCase):
    def test_catalog_and_default_none(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, capsule = create_collection(
                Path(temporary) / "vault"
            )
            records, warnings = scan_save_sets(
                root,
                capsule_path=capsule,
                capsule_id=CAPSULE_ID,
            )
            self.assertEqual(warnings, ())
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].save_set_id, "fixture-save")
            contract = json.loads(
                (
                    root
                    / "03_PERSISTENT_STATE"
                    / "SAVE_LIBRARY_CONTRACT.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(contract["default_selection"], "none")

    def test_definition_digest_ignores_noncontract_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, capsule = create_collection(
                Path(temporary) / "vault"
            )
            document = json.loads(
                capsule.read_text(encoding="utf-8")
            )
            declaration = document["persistent_state"][0]
            declaration["description"] = (
                "Documentary text outside the contractual digest."
            )
            declaration["x-gui-note"] = {
                "source": "fixture",
                "preserved": True,
            }
            capsule.write_text(
                json.dumps(
                    document,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            records, warnings = scan_save_sets(
                root,
                capsule_path=capsule,
                capsule_id=CAPSULE_ID,
            )

            self.assertEqual(warnings, ())
            self.assertEqual(
                [record.save_set_id for record in records],
                ["fixture-save"],
            )

    def test_selected_save_composes_full_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, capsule = create_collection(base / "vault")
            runner = runners_by_id(root)["ge-proton11-1"]
            save_set = scan_save_sets(
                root,
                capsule_path=capsule,
                capsule_id=CAPSULE_ID,
            )[0][0]
            destination_parent = base / "destinations"
            destination_parent.mkdir()
            destination = resolve_destination(
                destination_parent,
                capsule_id=CAPSULE_ID,
                profile_id=PROFILE_ID,
                backend_id="direct-wine",
                runner=runner,
                save_set_id=save_set.save_set_id,
            )
            validated = validate_request(
                MaterializationRequest(
                    collection_root=root,
                    capsule_path=capsule,
                    capsule_id=CAPSULE_ID,
                    profile_id=PROFILE_ID,
                    backend_id="direct-wine",
                    runner=runner,
                    destination=destination,
                    save_set=save_set,
                )
            )
            with prepared_state_backup(validated) as prepared:
                self.assertEqual(
                    prepared.save_set_id,
                    save_set.save_set_id,
                )
                receipt = json.loads(
                    (
                        prepared.backup_path
                        / "state-backup.json"
                    ).read_text(encoding="utf-8")
                )
                item = receipt["items"][0]
                self.assertTrue(item["present"])
                self.assertEqual(item["entries"][0]["digest"], save_set.digest)
                payload = (
                    prepared.backup_path
                    / item["payload_path"]
                )
                self.assertEqual(
                    payload.read_bytes(),
                    save_set.payload_path.read_bytes(),
                )
            self.assertFalse(
                any(
                    destination_parent.glob(
                        ".ogv-state-selection-*"
                    )
                )
            )

    def test_selected_save_uses_ogv_sorted_state_order(self) -> None:
        """Compose against accepted items sorted by state ID, as OGV does."""

        def compact_digest(value: object) -> str:
            data = json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            import hashlib

            return "sha256:" + hashlib.sha256(data).hexdigest()

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, capsule = create_collection(base / "vault")

            document = json.loads(
                capsule.read_text(encoding="utf-8")
            )
            save_declaration = document["persistent_state"][0]
            config_declaration = {
                "id": "config",
                "path": "drive_c/config.ini",
                "kind": "configuration",
                "backup": True,
                "sensitive": False,
                "required": True,
            }

            # Documentary order intentionally differs from contractual order.
            document["persistent_state"] = [
                save_declaration,
                config_declaration,
            ]
            capsule.write_text(
                json.dumps(
                    document,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            accepted = (
                root
                / "03_PERSISTENT_STATE"
                / CAPSULE_ID
                / "accepted"
            )
            config_payload = b"fixture-config\n"
            config_digest = compact_digest(
                [
                    {
                        "path": ".",
                        "type": "file",
                        "mode": 0o600,
                        "bytes": len(config_payload),
                        "digest": (
                            "sha256:"
                            + __import__("hashlib")
                            .sha256(config_payload)
                            .hexdigest()
                        ),
                    }
                ]
            )
            config_container = (
                accepted / "payload" / "0000-config"
            )
            config_container.mkdir(mode=0o700)
            config_data = config_container / "data"
            config_data.write_bytes(config_payload)
            config_data.chmod(0o600)

            receipt_path = accepted / "state-backup.json"
            receipt = json.loads(
                receipt_path.read_text(encoding="utf-8")
            )
            config_entries = [
                {
                    "path": ".",
                    "type": "file",
                    "mode": 0o600,
                    "bytes": len(config_payload),
                    "digest": (
                        "sha256:"
                        + __import__("hashlib")
                        .sha256(config_payload)
                        .hexdigest()
                    ),
                }
            ]
            receipt["state_definition_digest"] = compact_digest(
                {
                    "capsule_id": CAPSULE_ID,
                    "persistent_state": [
                        config_declaration,
                        save_declaration,
                    ],
                }
            )
            receipt["items"] = [
                {
                    "id": "config",
                    "declared_path": "drive_c/config.ini",
                    "kind": "configuration",
                    "sensitive": False,
                    "required": True,
                    "present": True,
                    "entry_type": "file",
                    "payload_path":
                        "payload/0000-config/data",
                    "file_count": 1,
                    "directory_count": 0,
                    "bytes": len(config_payload),
                    "tree_digest": compact_digest(
                        config_entries
                    ),
                    "entries": config_entries,
                },
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
                },
            ]
            receipt_path.write_text(
                json.dumps(
                    receipt,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            runner = runners_by_id(root)["ge-proton11-1"]
            save_set = scan_save_sets(
                root,
                capsule_path=capsule,
                capsule_id=CAPSULE_ID,
            )[0][0]
            destination_parent = base / "destinations"
            destination_parent.mkdir()
            destination = resolve_destination(
                destination_parent,
                capsule_id=CAPSULE_ID,
                profile_id=PROFILE_ID,
                backend_id="direct-wine",
                runner=runner,
                save_set_id=save_set.save_set_id,
            )
            validated = validate_request(
                MaterializationRequest(
                    collection_root=root,
                    capsule_path=capsule,
                    capsule_id=CAPSULE_ID,
                    profile_id=PROFILE_ID,
                    backend_id="direct-wine",
                    runner=runner,
                    destination=destination,
                    save_set=save_set,
                )
            )

            with prepared_state_backup(validated) as prepared:
                composed = json.loads(
                    (
                        prepared.backup_path
                        / "state-backup.json"
                    ).read_text(encoding="utf-8")
                )
                self.assertEqual(
                    [item["id"] for item in composed["items"]],
                    ["config", "save"],
                )
                self.assertEqual(
                    composed["items"][1]["payload_path"],
                    "payload/0001-save/data",
                )
                self.assertTrue(
                    composed["items"][1]["present"]
                )
                self.assertEqual(
                    (
                        prepared.backup_path
                        / composed["items"][0]["payload_path"]
                    ).read_bytes(),
                    config_payload,
                )

    def test_names_separate_none_and_selected_save(self) -> None:
        none_name = variant_destination_name(
            CAPSULE_ID,
            PROFILE_ID,
            "direct-wine",
            "ge-proton11-1",
        )
        selected_name = variant_destination_name(
            CAPSULE_ID,
            PROFILE_ID,
            "direct-wine",
            "ge-proton11-1",
            "fixture-save",
        )
        self.assertNotEqual(none_name, selected_name)
        self.assertIn("--save-fixture-save", selected_name)


if __name__ == "__main__":
    unittest.main()
