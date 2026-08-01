#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

python3 -B - <<'PY'
from __future__ import annotations

import os
import sys
from pathlib import Path

from offline_game_vault_gui.config import resolve_collection_root
from offline_game_vault_gui.core import inspect_core
from offline_game_vault_gui.experimental_service import (
    discover_bottles_path,
    list_preserved_runners,
)


def result(label: str, status: str, detail: str = "") -> None:
    suffix = f": {detail}" if detail else ""
    print(f"{status:8} {label}{suffix}")


failed = False

if sys.version_info >= (3, 11):
    result("Python >= 3.11", "VERIFIED", sys.version.split()[0])
else:
    result("Python >= 3.11", "FAILED", sys.version.split()[0])
    failed = True

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gtk  # noqa: F401
except Exception as exc:
    result("GTK4/libadwaita bindings", "FAILED", str(exc))
    failed = True
else:
    result("GTK4/libadwaita bindings", "VERIFIED")

try:
    core = inspect_core()
except Exception as exc:
    result("Offline Game Vault core 0.11.3+", "FAILED", str(exc))
    failed = True
else:
    result(
        "Offline Game Vault core",
        "VERIFIED",
        f"{core.version} ({core.origin})",
    )

collection = resolve_collection_root().expanduser()
try:
    collection = collection.resolve(strict=True)
    required = (
        collection / "INDEX.json",
        collection / "01_IMMUTABLE_VAULT" / "VAULT_INVENTORY.json",
        collection / "02_CAPSULES",
    )
    if not all(
        path.exists() and not path.is_symlink()
        for path in required
    ):
        raise OSError("collection control plane is incomplete")
except OSError as exc:
    result("Collection", "PENDING", f"{collection}: {exc}")
else:
    result("Collection", "VERIFIED", str(collection))
    try:
        runners, warnings = list_preserved_runners(collection)
    except Exception as exc:
        result("Preserved runners", "FAILED", str(exc))
        failed = True
    else:
        result("Preserved runners", "VERIFIED", str(len(runners)))
        for warning in warnings:
            result("Runner warning", "PENDING", warning)


try:
    bottles = discover_bottles_path()
except Exception as exc:
    result("Managed Bottles directory", "PENDING", str(exc))
else:
    result("Managed Bottles directory", "VERIFIED", str(bottles))

bwrap = Path(os.environ.get("OGV_BWRAP", "/usr/bin/bwrap"))
if bwrap.is_file() and os.access(bwrap, os.X_OK):
    result("Bubblewrap", "VERIFIED", str(bwrap))
else:
    result(
        "Bubblewrap",
        "PENDING",
        "required only by core paths that use it",
    )

raise SystemExit(1 if failed else 0)
PY
