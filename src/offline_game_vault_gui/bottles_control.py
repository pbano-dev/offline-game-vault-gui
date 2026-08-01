from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class BottlesControlError(RuntimeError):
    pass


def validate_bottles_control(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BottlesControlError("Bottles control is not an object")
    return value


def write_bottles_control(path: Path, value: dict[str, Any]) -> None:
    validate_bottles_control(value)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, destination)


def refresh_bottles_control(
    path: Path,
    updates: dict[str, Any],
) -> dict[str, Any]:
    current: dict[str, Any] = {}
    if Path(path).is_file() and not Path(path).is_symlink():
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        current = validate_bottles_control(value)
    current.update(updates)
    write_bottles_control(path, current)
    return current
