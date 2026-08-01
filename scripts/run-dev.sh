#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

if [[ -z "${OGV_SOURCE_ROOT:-}" ]]; then
    SIBLING="$(cd -- "$ROOT/.." 2>/dev/null && pwd -P)/offline-game-vault"
    if [[ -d "$SIBLING/src/offline_game_vault" ]]; then
        export OGV_SOURCE_ROOT="$SIBLING"
    fi
fi

exec python3 -B -m offline_game_vault_gui "$@"
