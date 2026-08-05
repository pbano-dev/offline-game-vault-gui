from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
from typing import Any


APP_DIRECTORY = "offline-game-vault-gui"


def _xdg_path(variable: str, fallback: Path) -> Path:
    raw = os.environ.get(variable)
    return Path(raw).expanduser() if raw else fallback


def _string(value: Any) -> str:
    return value if isinstance(value, str) else ""


@dataclass(slots=True)
class Preferences:
    collection_root: str = ""
    destination_parent: str = ""
    core_source_root: str = ""

    @classmethod
    def load(cls) -> "Preferences":
        path = cls.path()
        if path.is_symlink() or not path.is_file():
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

    @classmethod
    def path(cls) -> Path:
        config_home = _xdg_path(
            "XDG_CONFIG_HOME",
            Path.home() / ".config",
        )
        return config_home / APP_DIRECTORY / "preferences.json"

    def save(self) -> None:
        path = self.path()
        if path.exists() and path.is_symlink():
            raise OSError("Preferences path is a symbolic link")
        path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(
            json.dumps(
                asdict(self),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.chmod(0o600)
        os.replace(temporary, path)
