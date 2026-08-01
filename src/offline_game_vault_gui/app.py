"""Compatibility entry point for the unified 0.3.3 GUI.

The operational implementation lives in :mod:`integrated_app`.  This module
remains importable for callers that used ``offline_game_vault_gui.app`` before
0.3.3.
"""

from .integrated_app import (
    IntegratedMainWindow as MainWindow,
    VaultApplication,
    main,
)

__all__ = ["MainWindow", "VaultApplication", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
