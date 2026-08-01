from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class WindowsExportError(RuntimeError):
    pass


def transform_base_to_windows_export(
    destination: Path,
    metadata: dict[str, Any],
) -> Path:
    root = Path(destination)
    if root.is_symlink() or not root.is_dir():
        raise WindowsExportError(
            "Windows export destination is not a regular directory"
        )
    receipt = root / "WINDOWS_EXPORT_CANDIDATE.json"
    receipt.write_text(
        json.dumps(
            {
                "schema": 0,
                "status": "candidate-not-functionally-tested",
                "metadata": metadata,
            },
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return receipt
