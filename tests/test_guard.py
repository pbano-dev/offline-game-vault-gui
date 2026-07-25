from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from offline_game_vault_gui.guard import (
    GuardError,
    resolve_destination,
    validate_request,
    variant_destination_name,
)
from offline_game_vault_gui.model import MaterializationRequest

from helpers import (
    CAPSULE_ID,
    GE_RUNNER_ID,
    PROFILE_ID,
    SODA_RUNNER_ID,
    create_collection,
    create_playable_destination,
    runners_by_id,
)


class GuardTests(unittest.TestCase):
    def _request(
        self,
        root: Path,
        capsule: Path,
        parent: Path,
        profile_id: str,
        *,
        backend_id: str,
        runner_id: str | None = None,
    ) -> MaterializationRequest:
        runner = (
            runners_by_id(root)[runner_id]
            if runner_id is not None
            else None
        )
        destination = resolve_destination(
            parent,
            capsule_id=CAPSULE_ID,
            profile_id=profile_id,
            backend_id=backend_id,  # type: ignore[arg-type]
            runner=runner,
        )
        return MaterializationRequest(
            collection_root=root,
            capsule_path=capsule,
            capsule_id=CAPSULE_ID,
            profile_id=profile_id,
            backend_id=backend_id,  # type: ignore[arg-type]
            runner=runner,
            destination=destination,
        )

    def test_default_direct_wine_is_original_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, capsule = create_collection(base / "vault")
            parent = base / "destinations"
            parent.mkdir()

            validated = validate_request(
                self._request(
                    root,
                    capsule,
                    parent,
                    PROFILE_ID,
                    backend_id="direct-wine",
                    runner_id=GE_RUNNER_ID,
                )
            )
            self.assertEqual(validated.mode, "playable")
            self.assertEqual(validated.default_runner_id, GE_RUNNER_ID)
            self.assertFalse(validated.overlay_required)
            self.assertFalse(validated.reusable)
            self.assertEqual(validated.runner.runner_id, GE_RUNNER_ID)

    def test_soda_requires_derived_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, capsule = create_collection(base / "vault")
            parent = base / "destinations"
            parent.mkdir()

            validated = validate_request(
                self._request(
                    root,
                    capsule,
                    parent,
                    PROFILE_ID,
                    backend_id="direct-wine",
                    runner_id=SODA_RUNNER_ID,
                )
            )
            self.assertTrue(validated.overlay_required)
            self.assertEqual(validated.default_runner_id, GE_RUNNER_ID)
            self.assertEqual(validated.runner.runner_id, SODA_RUNNER_ID)
            self.assertIn(SODA_RUNNER_ID, validated.destination.name)

    def test_base_accepts_profile_without_runner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, capsule = create_collection(base / "vault")
            parent = base / "destinations"
            parent.mkdir()

            validated = validate_request(
                self._request(
                    root,
                    capsule,
                    parent,
                    "linux-base-only",
                    backend_id="base",
                )
            )
            self.assertEqual(validated.mode, "base")
            self.assertIsNone(validated.state_backup)
            self.assertIsNone(validated.runner)

    def test_direct_wine_resolves_accepted_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, capsule = create_collection(base / "vault")
            parent = base / "destinations"
            parent.mkdir()

            validated = validate_request(
                self._request(
                    root,
                    capsule,
                    parent,
                    PROFILE_ID,
                    backend_id="direct-wine",
                    runner_id=SODA_RUNNER_ID,
                )
            )
            self.assertEqual(
                validated.state_backup,
                root
                / "03_PERSISTENT_STATE"
                / CAPSULE_ID
                / "accepted",
            )

    def test_rejects_destination_inside_collection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, capsule = create_collection(Path(temporary) / "vault")
            inside = root / "destinations"
            inside.mkdir()

            with self.assertRaises(GuardError):
                validate_request(
                    self._request(
                        root,
                        capsule,
                        inside,
                        PROFILE_ID,
                        backend_id="direct-wine",
                        runner_id=GE_RUNNER_ID,
                    )
                )

    def test_reuses_only_matching_runner_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, capsule = create_collection(base / "vault")
            parent = base / "destinations"
            parent.mkdir()
            runners = runners_by_id(root)
            soda = runners[SODA_RUNNER_ID]

            destination = parent / variant_destination_name(
                CAPSULE_ID,
                PROFILE_ID,
                "direct-wine",
                SODA_RUNNER_ID,
            )
            create_playable_destination(destination, soda)

            validated = validate_request(
                self._request(
                    root,
                    capsule,
                    parent,
                    PROFILE_ID,
                    backend_id="direct-wine",
                    runner_id=SODA_RUNNER_ID,
                )
            )
            self.assertTrue(validated.reusable)

            ge_request = self._request(
                root,
                capsule,
                parent,
                PROFILE_ID,
                backend_id="direct-wine",
                runner_id=GE_RUNNER_ID,
            )
            self.assertNotEqual(ge_request.destination, destination)
            self.assertFalse(validate_request(ge_request).reusable)

    def test_rejects_existing_base_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, capsule = create_collection(base / "vault")
            parent = base / "destinations"
            parent.mkdir()
            request = self._request(
                root,
                capsule,
                parent,
                "linux-base-only",
                backend_id="base",
            )
            request.destination.mkdir()

            with self.assertRaises(GuardError):
                validate_request(request)

    def test_variant_names_separate_runners(self) -> None:
        ge = variant_destination_name(
            CAPSULE_ID,
            PROFILE_ID,
            "direct-wine",
            GE_RUNNER_ID,
        )
        soda = variant_destination_name(
            CAPSULE_ID,
            PROFILE_ID,
            "direct-wine",
            SODA_RUNNER_ID,
        )
        self.assertNotEqual(ge, soda)


if __name__ == "__main__":
    unittest.main()
