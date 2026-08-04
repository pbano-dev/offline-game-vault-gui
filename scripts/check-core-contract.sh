#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
CORE_ROOT="${1:-${OGV_SOURCE_ROOT:-"$ROOT/../offline-game-vault"}}"

if [[ ! -f "$CORE_ROOT/src/offline_game_vault/cli.py" ]]; then
    echo "ERROR: no compatible core checkout at the selected path" >&2
    exit 1
fi

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONDONTWRITEBYTECODE=1
export OGV_SOURCE_ROOT="$CORE_ROOT"

python3 -B - <<'PY_CORE_PROBE'
from pathlib import Path
import os

from offline_game_vault_gui.core import CoreClient

client = CoreClient.resolve(
    source_root=Path(os.environ["OGV_SOURCE_ROOT"]),
)
probe = client.probe()

print(f"Real core contract: compatible ({probe.version})")
PY_CORE_PROBE
