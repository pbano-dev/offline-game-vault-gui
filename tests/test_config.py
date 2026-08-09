from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from offline_game_vault_gui.config import Preferences


class PreferencesTests(unittest.TestCase):
    def test_round_trip_uses_xdg_config_home(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            environment = {
                "XDG_CONFIG_HOME": temporary,
                "OGV_COLLECTION_ROOT": "",
                "OGV_DESTINATION_PARENT": "",
                "OGV_SOURCE_ROOT": "",
            }
            with patch.dict(os.environ, environment, clear=False):
                value = Preferences(
                    collection_root="/collection",
                    destination_parent="/derived",
                    core_source_root="/core",
                )
                value.save()
                loaded = Preferences.load()
                path = Preferences.path()

            self.assertEqual(loaded, value)
            self.assertEqual(
                stat.S_IMODE(path.stat().st_mode),
                0o600,
            )
            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(document["core_source_root"], "/core")

    def test_environment_is_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with patch.dict(
                os.environ,
                {
                    "XDG_CONFIG_HOME": temporary,
                    "OGV_COLLECTION_ROOT": "/collection",
                    "OGV_DESTINATION_PARENT": "/derived",
                    "OGV_SOURCE_ROOT": "/core",
                },
                clear=False,
            ):
                loaded = Preferences.load()
            self.assertEqual(loaded.collection_root, "/collection")


if __name__ == "__main__":
    unittest.main()
