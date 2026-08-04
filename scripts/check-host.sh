#!/usr/bin/env bash
set -Eeuo pipefail

python3 - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit("Python 3.11 or newer is required.")
print(sys.version.split()[0])
PY

python3 - <<'PY'
try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gtk  # noqa: F401
except Exception as exc:
    raise SystemExit(f"GTK4/libadwaita/PyGObject unavailable: {exc}")
print("GTK4/libadwaita/PyGObject: available")
PY

PYTHONPATH="${PYTHONPATH:-}:$(pwd)/src" \
python3 - <<'PY'
from offline_game_vault_gui.core import CoreClient
client = CoreClient.resolve()
probe = client.probe()
print(f"Core: {probe.version} ({probe.description})")
PY
