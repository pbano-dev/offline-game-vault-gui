#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1

gui_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
repo_root="${OGV_SOURCE_ROOT:-}"

if [[ -z "$repo_root" ]]; then
    sibling_candidate="$gui_root/../offline-game-vault"
    parent_candidate="$gui_root/.."

    if [[ -f "$sibling_candidate/pyproject.toml" \
       && -f "$sibling_candidate/src/offline_game_vault/cli.py" ]]; then
        candidate="$sibling_candidate"
    elif [[ -f "$parent_candidate/pyproject.toml" \
         && -f "$parent_candidate/src/offline_game_vault/cli.py" ]]; then
        candidate="$parent_candidate"
    else
        printf '%s\n' \
            'ERROR: offline-game-vault was not found.' \
            'Set OGV_SOURCE_ROOT to a compatible source checkout.' >&2
        exit 2
    fi

    repo_root="$(cd -- "$candidate" && pwd -P)"
else
    [[ -d "$repo_root" && ! -L "$repo_root" ]] || {
        printf 'ERROR: OGV_SOURCE_ROOT is not a regular directory\n' >&2
        exit 2
    }
    repo_root="$(cd -- "$repo_root" && pwd -P)"
fi

[[ -f "$repo_root/pyproject.toml" \
   && -f "$repo_root/src/offline_game_vault/cli.py" ]] || {
    printf 'ERROR: incomplete offline-game-vault source checkout\n' >&2
    exit 2
}

export PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -B -c \
  'from offline_game_vault.cli import main; raise SystemExit(main())' \
  "$@"
