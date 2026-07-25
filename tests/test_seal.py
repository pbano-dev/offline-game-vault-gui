from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from offline_game_vault_gui.seal import capture_collection_seal

from helpers import create_collection


class SealTests(unittest.TestCase):
    def test_detects_change(self) -> None:
        with TemporaryDirectory() as temporary:
            root, capsule = create_collection(Path(temporary) / "vault")
            before = capture_collection_seal(root, capsule)
            (root / "INDEX.json").write_text(
                '{"changed":true}\n',
                encoding="utf-8",
            )
            after = capture_collection_seal(root, capsule)
            self.assertNotEqual(before, after)


if __name__ == "__main__":
    unittest.main()
