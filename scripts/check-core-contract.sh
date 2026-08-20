#!/usr/bin/env bash
set -Eeuo pipefail

if (($# != 1)); then
    echo "Usage: $0 <offline-game-vault-checkout>" >&2
    exit 2
fi

CORE="$(cd -- "$1" && pwd -P)"
CLI="$CORE/src/offline_game_vault/cli.py"

if [[ ! -f "$CLI" || -L "$CLI" ]]; then
    echo "ERROR: core checkout has no regular CLI module" >&2
    exit 1
fi

export PYTHONPATH="$CORE/src${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONDONTWRITEBYTECODE=1

version="$(python3 -B -m offline_game_vault.cli --version)"
help="$(python3 -B -m offline_game_vault.cli compose --help)"
state_help="$(
    python3 -B -m offline_game_vault.cli         verify-state-backup --help
)"

python3 -B - "$version" "$help" "$state_help" <<'PY'
from __future__ import annotations
import re
import sys

version_text = sys.argv[1]
help_text = sys.argv[2]
state_help_text = sys.argv[3]
match = re.search(r"\b(\d+)\.(\d+)\.(\d+)\b", version_text)
if match is None:
    raise SystemExit(f"Cannot parse core version: {version_text!r}")
version = tuple(int(value) for value in match.groups())
if version < (0, 19, 0):
    raise SystemExit(
        f"Core {'.'.join(match.groups())} is too old; 0.19.0+ required"
    )
for token in (
    "--backend",
    "--runner",
    "--state-backup",
    "--no-state",
    "--save-id",
    "--bottles-path",
    "--bottle-name",
    "--destination",
    "--json",
):
    if token not in help_text:
        raise SystemExit(f"compose help lacks {token}")
for token in ("--capsule", "--backup", "--json"):
    if token not in state_help_text:
        raise SystemExit(
            f"verify-state-backup help lacks {token}"
        )
print(
    "CORE CONTRACT PASSED: "
    f"version={'.'.join(match.groups())}, "
    "backend-neutral-state=yes, explicit-no-state=yes"
)
PY
