#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
export PYTHONDONTWRITEBYTECODE=1

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
export PYTHONPATH="${project_root}/src${PYTHONPATH:+:${PYTHONPATH}}"

if [[ -z "${OGV_EXECUTABLE:-}" ]] && ! command -v ogv >/dev/null 2>&1; then
    export OGV_EXECUTABLE="$project_root/scripts/ogv-source-wrapper.sh"
fi

exec python3 -B -m offline_game_vault_gui
