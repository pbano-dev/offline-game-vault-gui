from __future__ import annotations

import unittest

from offline_game_vault_gui.umu_service import (
    UmuServiceError,
    _materialization_result_payload,
)


class UmuMaterializationJsonContractTests(unittest.TestCase):
    def test_unwraps_current_core_materialization_envelope(self) -> None:
        result = {
            "backend": "umu",
            "profile_id": "linux-umu-test",
            "selected_save": None,
            "complete": True,
        }
        self.assertIs(
            _materialization_result_payload(
                {"materialization": result}
            ),
            result,
        )

    def test_accepts_direct_result_for_compatibility(self) -> None:
        result = {
            "backend": "umu",
            "profile_id": "linux-umu-test",
            "selected_save": None,
            "complete": True,
        }
        self.assertIs(
            _materialization_result_payload(result),
            result,
        )

    def test_rejects_non_umu_or_missing_result(self) -> None:
        with self.assertRaises(UmuServiceError):
            _materialization_result_payload(
                {"materialization": "invalid"}
            )


if __name__ == "__main__":
    unittest.main()
