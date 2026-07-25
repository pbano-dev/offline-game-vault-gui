#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
if [[ -n "${OGV_COLLECTION_ROOT:-}" ]]; then
    collection_root="$OGV_COLLECTION_ROOT"
elif [[ -r "/run/media/system/Games/OfflineGameVault/INDEX.json" ]]; then
    collection_root="/run/media/system/Games/OfflineGameVault"
else
    collection_root="${HOME:?HOME is not defined}/Games/OfflineGameVault"
fi
bwrap_path="${OGV_BWRAP:-/usr/bin/bwrap}"
ogv_path="${OGV_EXECUTABLE:-}"
state_bridge="${OGV_STATE_BRIDGE:-$project_root/scripts/ogv-state-capsule-bridge.py}"
status=0

if command -v python3 >/dev/null 2>&1; then
    printf 'VERIFIED: python3 -> %s\n' "$(command -v python3)"
else
    printf 'MISSING: python3\n' >&2
    status=1
fi

if [[ -x "$bwrap_path" && ! -d "$bwrap_path" ]]; then
    printf 'VERIFIED: bubblewrap -> %s\n' "$bwrap_path"
else
    printf 'MISSING: executable bubblewrap -> %s\n' "$bwrap_path" >&2
    status=1
fi

if [[ -z "$ogv_path" ]] && command -v ogv >/dev/null 2>&1; then
    ogv_path="$(command -v ogv)"
fi
if [[ -z "$ogv_path" \
      && -x "$project_root/scripts/ogv-source-wrapper.sh" ]]; then
    sibling_root="$project_root/../offline-game-vault"
    parent_root="$project_root/.."

    if [[ -f "$sibling_root/pyproject.toml" \
       && -f "$sibling_root/src/offline_game_vault/cli.py" ]]; then
        ogv_path="$project_root/scripts/ogv-source-wrapper.sh"
        printf 'VERIFIED: sibling offline-game-vault checkout detected\n'
    elif [[ -f "$parent_root/pyproject.toml" \
         && -f "$parent_root/src/offline_game_vault/cli.py" ]]; then
        ogv_path="$project_root/scripts/ogv-source-wrapper.sh"
        printf 'VERIFIED: parent offline-game-vault checkout detected\n'
    fi
fi

if [[ -n "$ogv_path" && -x "$ogv_path" && ! -d "$ogv_path" ]]; then
    help_text="$("$ogv_path" --help 2>&1 || true)"
    missing_commands=()
    for required in \
        materialize \
        materialize-playable \
        verify-playable \
        run-playable \
        deploy-bottles \
        verify-bottles-deployment \
        run-bottles
    do
        grep -q -- "$required" <<<"$help_text" || \
            missing_commands+=("$required")
    done
    if ((${#missing_commands[@]} == 0)); then
        printf 'VERIFIED: core with materialization and execution -> %s\n' \
            "$ogv_path"
    else
        printf 'MISSING: OGV commands: %s\n' \
            "${missing_commands[*]}" >&2
        status=1
    fi
else
    printf 'MISSING: ogv is unavailable\n' >&2
    status=1
fi

if [[ -x "$state_bridge" && ! -d "$state_bridge" ]]; then
    if "$state_bridge" --help >/dev/null 2>&1; then
        printf 'VERIFIED: state bridge for overlays -> %s\n' \
            "$state_bridge"
    else
        printf 'MISSING: state bridge does not respond to --help -> %s\n' \
            "$state_bridge" >&2
        status=1
    fi
else
    printf 'MISSING: executable state bridge -> %s\n' \
        "$state_bridge" >&2
    status=1
fi


if command -v flatpak >/dev/null 2>&1; then
    bottles_cli=(
        "$(command -v flatpak)"
        run
        --command=bottles-cli
        com.usebottles.bottles
    )
    if "${bottles_cli[@]}" --json info bottles-path >/dev/null 2>&1 \
       && "${bottles_cli[@]}" --json list components \
            -f category:runners >/dev/null 2>&1; then
        printf 'VERIFIED: Bottles Flatpak and bottles-cli\n'
    else
        printf 'WARNING: Bottles is unavailable; the Bottles backend will be disabled\n' >&2
    fi
else
    printf 'WARNING: flatpak is unavailable; the Bottles backend will be disabled\n' >&2
fi

gtk_probe='
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk
gtk = ".".join(map(str, (
    Gtk.get_major_version(),
    Gtk.get_minor_version(),
    Gtk.get_micro_version(),
)))
adw = ".".join(map(str, (
    Adw.get_major_version(),
    Adw.get_minor_version(),
    Adw.get_micro_version(),
)))
print(f"VERIFIED: GTK {gtk}; libadwaita {adw}")
'
if python3 -B -c "$gtk_probe"; then
    :
else
    printf 'MISSING: PyGObject, GTK 4, or libadwaita\n' >&2
    status=1
fi

if [[ -L "$collection_root" ]]; then
    printf 'ERROR: the collection is a symbolic link\n' >&2
    status=1
elif [[ -r "$collection_root/01_IMMUTABLE_VAULT/VAULT_INVENTORY.json" \
     && -r "$collection_root/INDEX.json" \
     && -d "$collection_root/02_CAPSULES" \
     && -d "$collection_root/03_PERSISTENT_STATE" \
     && -d "$collection_root/04_RECEIPTS" ]]; then
    printf 'VERIFIED: minimum structure -> %s\n' "$collection_root"
else
    printf 'MISSING: readable collection or minimum structure -> %s\n' \
        "$collection_root" >&2
    status=1
fi

exit "$status"
