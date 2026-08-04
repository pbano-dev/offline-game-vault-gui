from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from offline_game_vault_gui.config import Preferences


class PreferencesTests(unittest.TestCase):
    def test_round_trip_uses_private_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with patch.dict(
                os.environ,
                {"XDG_CONFIG_HOME": temporary},
                clear=False,
            ):
                preferences = Preferences(
                    collection_root="/collection",
                    destination_parent="/destination",
                    core_source_root="/core",
                )
                path = preferences.save()
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                loaded = Preferences.load()
                self.assertEqual(loaded, preferences)
                document = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(document["schema"], 1)

    def test_environment_is_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with patch.dict(
                os.environ,
                {
                    "XDG_CONFIG_HOME": temporary,
                    "OGV_COLLECTION_ROOT": "/collection",
                    "OGV_DESTINATION_PARENT": "/destination",
                },
                clear=False,
            ):
                loaded = Preferences.load()
                self.assertEqual(loaded.collection_root, "/collection")
                self.assertEqual(
                    loaded.destination_parent,
                    "/destination",
                )


if __name__ == "__main__":
    unittest.main()
