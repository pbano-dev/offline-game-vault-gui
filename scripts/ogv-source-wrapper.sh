#!/usr/bin/env bash
set -Eeuo pipefail

SOURCE_ROOT="${OGV_SOURCE_ROOT:?OGV_SOURCE_ROOT is required}"
[[ -d "$SOURCE_ROOT/src/offline_game_vault" ]] || {
    printf 'ERROR: invalid OGV_SOURCE_ROOT: %s\n' "$SOURCE_ROOT" >&2
    exit 2
}

export PYTHONPATH="$SOURCE_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -B -m offline_game_vault.cli "$@"
