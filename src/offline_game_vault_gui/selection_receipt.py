from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class SelectionReceiptError(RuntimeError):
    pass


DIRECT_RELATIVE = ".ogv-gui-selection.json"
DERIVATIVE_RELATIVE = ".ogv-gui-selection.json"


def write_selection_receipt(
    destination: Path,
    document: dict[str, Any],
) -> Path:
    if not isinstance(document, dict):
        raise SelectionReceiptError("Receipt is not an object")
    path = Path(destination) / DIRECT_RELATIVE
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(
            document,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return path
