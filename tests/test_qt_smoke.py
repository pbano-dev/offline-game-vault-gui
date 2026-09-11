from __future__ import annotations

import importlib.util
import os
import unittest


PYSIDE_AVAILABLE = importlib.util.find_spec("PySide6") is not None


@unittest.skipUnless(
    PYSIDE_AVAILABLE,
    "PySide6 is not installed in this test environment",
)
class QtSmokeTests(unittest.TestCase):
    def test_window_constructs_offscreen(self) -> None:
        os.environ.setdefault(
            "QT_QPA_PLATFORM",
            "offscreen",
        )
        from PySide6.QtWidgets import QApplication
        from offline_game_vault_gui.app import MainWindow
        from offline_game_vault_gui.config import Preferences

        application = QApplication.instance() or QApplication([])
        window = MainWindow(
            preferences=Preferences(),
            service=None,
            probe=None,
            startup_error="synthetic startup",
        )
        self.assertIn(
            "Offline Game Vault",
            window.windowTitle(),
        )
        self.assertTrue(window.windows_status.isHidden())
        window.close()
        application.processEvents()


if __name__ == "__main__":
    unittest.main()
