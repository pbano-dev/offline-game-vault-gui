from __future__ import annotations

import importlib.util
import os
import unittest


HAS_PYSIDE6 = importlib.util.find_spec("PySide6") is not None


@unittest.skipUnless(HAS_PYSIDE6, "PySide6 is not installed")
class QtSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        cls.application = QApplication.instance() or QApplication([])

    def test_long_selected_title_is_not_elided(self) -> None:
        from PySide6.QtCore import Qt
        from offline_game_vault_gui.app import RichComboBox

        combo = RichComboBox()
        title = (
            "A deliberately very long preserved game title that must remain "
            "fully visible in the Qt selector without an ellipsis"
        )
        combo.resize(340, 40)
        combo.add_rich_item(title, "steam-example-game")
        combo.setCurrentIndex(0)
        combo._update_height()
        self.assertEqual(
            combo.view().textElideMode(),
            Qt.TextElideMode.ElideNone,
        )
        self.assertGreater(combo.minimumHeight(), 40)
        self.assertEqual(combo.currentText(), title)


if __name__ == "__main__":
    unittest.main()
