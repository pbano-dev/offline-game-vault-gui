from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any


APP_DIRECTORY = "offline-game-vault-gui"


def _xdg_path(variable: str, fallback: Path) -> Path:
    raw = os.environ.get(variable)
    return Path(raw).expanduser() if raw else fallback


@dataclass(slots=True)
class Preferences:
    collection_root: str = ""
    destination_parent: str = ""
    core_source_root: str = ""

    @classmethod
    def load(cls) -> "Preferences":
        config_home = _xdg_path(
            "XDG_CONFIG_HOME",
            Path.home() / ".config",
        )
        path = config_home / APP_DIRECTORY / "preferences.json"
        if not path.is_file() or path.is_symlink():
            return cls.from_environment()
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return cls.from_environment()
        if not isinstance(value, dict):
            return cls.from_environment()
        return cls(
            collection_root=_string(value.get("collection_root"))
            or os.environ.get("OGV_COLLECTION_ROOT", ""),
            destination_parent=_string(value.get("destination_parent"))
            or os.environ.get("OGV_DESTINATION_PARENT", ""),
            core_source_root=_string(value.get("core_source_root"))
            or os.environ.get("OGV_SOURCE_ROOT", ""),
        )

    @classmethod
    def from_environment(cls) -> "Preferences":
        return cls(
            collection_root=os.environ.get("OGV_COLLECTION_ROOT", ""),
            destination_parent=os.environ.get("OGV_DESTINATION_PARENT", ""),
            core_source_root=os.environ.get("OGV_SOURCE_ROOT", ""),
        )

    def save(self) -> Path:
        config_home = _xdg_path(
            "XDG_CONFIG_HOME",
            Path.home() / ".config",
        )
        directory = config_home / APP_DIRECTORY
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = directory / "preferences.json"
        document = {
            "schema": 1,
            "collection_root": self.collection_root,
            "destination_parent": self.destination_parent,
            "core_source_root": self.core_source_root,
        }
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(document, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.chmod(0o600)
        temporary.replace(path)
        return path


def _string(value: Any) -> str:
    return value if isinstance(value, str) else ""
