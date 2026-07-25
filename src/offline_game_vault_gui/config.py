from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


PREFERRED_COLLECTION_ROOT = Path(
    "/run/media/system/Games/OfflineGameVault"
)
FALLBACK_COLLECTION_ROOT = (
    Path.home() / "Games" / "OfflineGameVault"
)
CONFIG_RELATIVE = Path(
    "offline-game-vault-gui"
) / "config.json"


class ConfigurationError(RuntimeError):
    pass


def _config_path() -> Path:
    configured = os.environ.get("XDG_CONFIG_HOME")
    root = (
        Path(configured)
        if configured
        else Path.home() / ".config"
    )
    return root / CONFIG_RELATIVE


def _read_configured_collection_root() -> Path | None:
    path = _config_path()

    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise ConfigurationError(
            "The configuration file is not a regular file"
        )

    try:
        document: Any = json.loads(
            path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError(
            "The configuration file is not valid JSON"
        ) from exc

    if not isinstance(document, dict):
        raise ConfigurationError(
            "The configuration file does not contain an object"
        )

    value = document.get("collection_root")

    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value.strip()
        or "\x00" in value
    ):
        raise ConfigurationError(
            "collection_root is not a valid path"
        )

    return Path(value).expanduser()


def _looks_like_collection(path: Path) -> bool:
    return (
        path.is_dir()
        and not path.is_symlink()
        and (path / "INDEX.json").is_file()
        and (
            path
            / "01_IMMUTABLE_VAULT"
            / "VAULT_INVENTORY.json"
        ).is_file()
        and (path / "02_CAPSULES").is_dir()
        and (path / "03_PERSISTENT_STATE").is_dir()
    )


def resolve_collection_root() -> Path:
    environment = os.environ.get("OGV_COLLECTION_ROOT")

    if environment:
        return Path(environment).expanduser()

    configured = _read_configured_collection_root()

    if configured is not None:
        return configured

    for candidate in (
        PREFERRED_COLLECTION_ROOT,
        FALLBACK_COLLECTION_ROOT,
    ):
        if _looks_like_collection(candidate):
            return candidate

    # The known collection location is on the mounted volume.
    # It remains the initial value even when the volume is not
    # mounted yet, so errors display the useful expected path.
    return PREFERRED_COLLECTION_ROOT
