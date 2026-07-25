from __future__ import annotations

import tempfile
import unittest
import json
import os
from pathlib import Path

from offline_game_vault_gui.runner_override import (
    RunnerOverrideError,
    build_derived_capsule,
)

from helpers import (
    GE_RUNNER_ID,
    PROFILE_ID,
    SODA_RUNNER_ID,
    create_collection,
    runners_by_id,
)


class RunnerOverrideTests(unittest.TestCase):
    def test_default_runner_keeps_original_capsule_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, capsule = create_collection(Path(temporary) / "vault")
            ge = runners_by_id(root)[GE_RUNNER_ID]
            derived = build_derived_capsule(capsule, PROFILE_ID, ge)

            self.assertFalse(derived.changed)
            self.assertEqual(derived.original_runner_id, GE_RUNNER_ID)
            self.assertEqual(derived.effective_status, "verified")

    def test_soda_creates_unaccepted_temporary_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, capsule = create_collection(Path(temporary) / "vault")
            soda = runners_by_id(root)[SODA_RUNNER_ID]
            derived = build_derived_capsule(capsule, PROFILE_ID, soda)

            self.assertTrue(derived.changed)
            profile = next(
                item
                for item in derived.document["profiles"]
                if item["id"] == PROFILE_ID
            )
            self.assertEqual(profile["status"], "not_tested")
            self.assertNotIn("acceptance_report", profile)
            self.assertEqual(
                profile["host_contract"],
                "host-contracts/linux-direct-wine.json",
            )
            self.assertIn(SODA_RUNNER_ID, profile["dependencies"])
            self.assertNotIn(GE_RUNNER_ID, profile["dependencies"])

            paths = profile["playable"]["paths"]
            self.assertEqual(paths["runner"], f"runner/{SODA_RUNNER_ID}")
            self.assertEqual(
                paths["wine"],
                f"runner/{SODA_RUNNER_ID}/bin/wine",
            )
            layout = profile["playable"]["layout"]
            runner_mapping = next(
                item for item in layout if item["object"] == SODA_RUNNER_ID
            )
            self.assertEqual(runner_mapping["source"], SODA_RUNNER_ID)

            declarations = {
                item["id"]: item for item in derived.document["objects"]
            }
            self.assertIn(GE_RUNNER_ID, declarations)
            self.assertIn(SODA_RUNNER_ID, declarations)
            self.assertEqual(
                declarations[SODA_RUNNER_ID]["digest"],
                soda.digest,
            )


    def test_overlay_carries_exact_nested_host_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, capsule = create_collection(Path(temporary) / "vault")
            soda = runners_by_id(root)[SODA_RUNNER_ID]
            source = (
                capsule.parent
                / "host-contracts/linux-direct-wine.json"
            )

            derived = build_derived_capsule(capsule, PROFILE_ID, soda)

            self.assertEqual(len(derived.companion_files), 1)
            companion = derived.companion_files[0]
            self.assertEqual(
                companion.relative_path,
                "host-contracts/linux-direct-wine.json",
            )
            self.assertEqual(companion.payload, source.read_bytes())
            self.assertEqual(companion.mode, 0o600)

    def test_rejects_host_contract_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, capsule = create_collection(Path(temporary) / "vault")
            document = json.loads(capsule.read_text(encoding="utf-8"))
            profile = next(
                item
                for item in document["profiles"]
                if item["id"] == PROFILE_ID
            )
            profile["host_contract"] = "../outside.json"
            capsule.write_text(
                json.dumps(document, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            (capsule.parent.parent / "outside.json").write_text(
                "{}\n",
                encoding="utf-8",
            )

            soda = runners_by_id(root)[SODA_RUNNER_ID]
            with self.assertRaisesRegex(
                RunnerOverrideError,
                "safe relative path",
            ):
                build_derived_capsule(capsule, PROFILE_ID, soda)

    def test_rejects_symlinked_host_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, capsule = create_collection(Path(temporary) / "vault")
            contract = (
                capsule.parent
                / "host-contracts/linux-direct-wine.json"
            )
            payload = contract.read_bytes()
            contract.unlink()
            target = capsule.parent / "real-host-contract.json"
            target.write_bytes(payload)
            os.symlink("../real-host-contract.json", contract)

            soda = runners_by_id(root)[SODA_RUNNER_ID]
            with self.assertRaisesRegex(
                RunnerOverrideError,
                "symbolic links",
            ):
                build_derived_capsule(capsule, PROFILE_ID, soda)


if __name__ == "__main__":
    unittest.main()
