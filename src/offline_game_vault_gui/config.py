from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


PREFERRED_COLLECTION_ROOT = Path(
    "/run/media/system/Games/OfflineGameVault"
)
FALLBACK_COLLECTION_ROOT = Path.home() / "Games" / "OfflineGameVault"
CONFIG_RELATIVE = Path("offline-game-vault-gui") / "config.json"


class ConfigurationError(RuntimeError):
    pass


def _config_path() -> Path:
    configured = os.environ.get("XDG_CONFIG_HOME")
    root = Path(configured) if configured else Path.home() / ".config"
    return root / CONFIG_RELATIVE


def _read_config() -> dict[str, Any]:
    path = _config_path()
    if not path.exists():
        return {}
    if path.is_symlink() or not path.is_file():
        raise ConfigurationError(
            "The configuration file is not a regular file"
        )
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError(
            "The configuration file is not valid JSON"
        ) from exc
    if not isinstance(document, dict):
        raise ConfigurationError(
            "The configuration file does not contain an object"
        )
    return document


def _path_value(document: dict[str, Any], key: str) -> Path | None:
    value = document.get(key)
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value.strip()
        or "\x00" in value
    ):
        raise ConfigurationError(f"{key} is not a valid path")
    return Path(value).expanduser()


def _looks_like_collection(path: Path) -> bool:
    return (
        path.is_dir()
        and not path.is_symlink()
        and (path / "INDEX.json").is_file()
        and (
            path / "01_IMMUTABLE_VAULT" / "VAULT_INVENTORY.json"
        ).is_file()
        and (path / "02_CAPSULES").is_dir()
        and (path / "03_PERSISTENT_STATE").is_dir()
    )


def resolve_collection_root() -> Path:
    environment = os.environ.get("OGV_COLLECTION_ROOT")
    if environment:
        return Path(environment).expanduser()

    configured = _path_value(_read_config(), "collection_root")
    if configured is not None:
        return configured

    for candidate in (
        PREFERRED_COLLECTION_ROOT,
        FALLBACK_COLLECTION_ROOT,
    ):
        if _looks_like_collection(candidate):
            return candidate
    return PREFERRED_COLLECTION_ROOT


def resolve_destination_parent() -> Path:
    environment = os.environ.get("OGV_DESTINATION_PARENT")
    if environment:
        return Path(environment).expanduser()

    configured = _path_value(_read_config(), "destination_parent")
    if configured is not None:
        return configured

    configured_data = os.environ.get("XDG_DATA_HOME")
    data_root = (
        Path(configured_data).expanduser()
        if configured_data
        else Path.home() / ".local" / "share"
    )
    return data_root / "offline-game-vault-gui" / "materializations"

