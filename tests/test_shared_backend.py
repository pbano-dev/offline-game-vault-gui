from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from offline_game_vault_gui.shared_backend import (
    SharedBackendError,
    scan_shared_bottles_backend,
)

from helpers import (
    BOTTLES_APP_COMMIT,
    BOTTLES_APP_REF,
    create_collection,
)


class SharedBackendTests(unittest.TestCase):
    def test_scans_bottles_backend_from_index_inventory_and_receipt(self) -> None:
        with TemporaryDirectory() as temporary:
            root, _capsule = create_collection(Path(temporary) / "vault")
            backend = scan_shared_bottles_backend(root)

            self.assertEqual(backend.role, "shared-backend")
            self.assertEqual(backend.application_ref, BOTTLES_APP_REF)
            self.assertEqual(backend.application_commit, BOTTLES_APP_COMMIT)
            self.assertEqual(backend.version, "64.1")
            self.assertTrue(
                (root / "01_IMMUTABLE_VAULT" / backend.archive_path).is_file()
            )

    def test_rejects_missing_physical_backend(self) -> None:
        with TemporaryDirectory() as temporary:
            root, _capsule = create_collection(Path(temporary) / "vault")
            backend = scan_shared_bottles_backend(root)
            (root / "01_IMMUTABLE_VAULT" / backend.archive_path).unlink()

            with self.assertRaises(SharedBackendError):
                scan_shared_bottles_backend(root)


if __name__ == "__main__":
    unittest.main()
