from __future__ import annotations

import unittest

from offline_game_vault_gui.logging_model import (
    make_record,
    matches_filter,
)


class LoggingTests(unittest.TestCase):
    def test_classifies_error_and_warning(self) -> None:
        error = make_record(
            "ERROR: failure",
            stream="stderr",
        )
        warning = make_record(
            "warning: notice",
            stream="stderr",
        )
        self.assertEqual(error.level, "ERROR")
        self.assertEqual(warning.level, "WARNING")

    def test_stream_fallback_and_filter(self) -> None:
        record = make_record(
            '{"complete": true}',
            stream="stdout",
        )
        self.assertEqual(record.level, "STDOUT")
        self.assertTrue(
            matches_filter(record, "STDOUT")
        )
        self.assertFalse(
            matches_filter(record, "ERROR")
        )


if __name__ == "__main__":
    unittest.main()
