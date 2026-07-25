from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from offline_game_vault_gui.config import (
    FALLBACK_COLLECTION_ROOT,
    PREFERRED_COLLECTION_ROOT,
    resolve_collection_root,
)


class ConfigurationTests(unittest.TestCase):
    def test_environment_has_priority(self) -> None:
        with patch.dict(
            os.environ,
            {"OGV_COLLECTION_ROOT": "/vault/from-env"},
            clear=False,
        ):
            self.assertEqual(
                resolve_collection_root(),
                Path("/vault/from-env"),
            )

    def test_config_has_priority_over_detection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_home = root / "config"
            config_path = (
                config_home
                / "offline-game-vault-gui"
                / "config.json"
            )
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                json.dumps(
                    {"collection_root": "/vault/from-config"}
                ),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {
                    "XDG_CONFIG_HOME": str(config_home),
                    "OGV_COLLECTION_ROOT": "",
                },
                clear=False,
            ):
                self.assertEqual(
                    resolve_collection_root(),
                    Path("/vault/from-config"),
                )

    def test_preferred_mounted_vault_is_selected(self) -> None:
        with patch.dict(
            os.environ,
            {"OGV_COLLECTION_ROOT": ""},
            clear=False,
        ), patch(
            "offline_game_vault_gui.config."
            "_read_configured_collection_root",
            return_value=None,
        ), patch(
            "offline_game_vault_gui.config._looks_like_collection",
            side_effect=lambda value: (
                value == PREFERRED_COLLECTION_ROOT
            ),
        ):
            self.assertEqual(
                resolve_collection_root(),
                PREFERRED_COLLECTION_ROOT,
            )

    def test_fallback_is_used_only_when_preferred_is_absent(self) -> None:
        with patch.dict(
            os.environ,
            {"OGV_COLLECTION_ROOT": ""},
            clear=False,
        ), patch(
            "offline_game_vault_gui.config."
            "_read_configured_collection_root",
            return_value=None,
        ), patch(
            "offline_game_vault_gui.config._looks_like_collection",
            side_effect=lambda value: (
                value == FALLBACK_COLLECTION_ROOT
            ),
        ):
            self.assertEqual(
                resolve_collection_root(),
                FALLBACK_COLLECTION_ROOT,
            )

    def test_missing_candidates_return_preferred_location(self) -> None:
        with patch.dict(
            os.environ,
            {"OGV_COLLECTION_ROOT": ""},
            clear=False,
        ), patch(
            "offline_game_vault_gui.config."
            "_read_configured_collection_root",
            return_value=None,
        ), patch(
            "offline_game_vault_gui.config._looks_like_collection",
            return_value=False,
        ):
            self.assertEqual(
                resolve_collection_root(),
                PREFERRED_COLLECTION_ROOT,
            )


if __name__ == "__main__":
    unittest.main()
