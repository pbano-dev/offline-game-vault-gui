# Offline Game Vault GUI — PySide6/Qt Widgets 0.5.0a1

Complete replacement source tree for the GTK4/libadwaita frontend. This branch
uses **PySide6 and Qt Widgets only** while preserving the state-free contract of
`offline-game-vault` 0.11.4 or newer.

The core remains authoritative for:

- immutable-object verification;
- runner and UMU component selection;
- Bottles, Direct-Wine, and UMU composition;
- writable materialization;
- generated `JUGAR.sh`, `VERIFICAR.sh`, and `DESINSTALAR.sh` operations.

The GUI remains a thin subprocess/JSON client:

```text
capsule.json -> catalog.py -> service.py -> core.py -> ogv
```

## Functional parity

The Qt frontend retains:

- collection-root and default-target selection;
- explicit core-checkout selection and validation;
- game, backend, source-layout, and preserved-runner selection;
- Bottles managed-path discovery;
- Direct-Wine and UMU target selection;
- UMU component-set diagnostics;
- additional Direct-Wine/UMU play arguments;
- generated Remove arguments;
- Materialize, Materialize & Play, Verify, Play, and Remove;
- private local operation receipts;
- background workers so long core operations do not block the interface.

The game selector renders the complete `game.title` with word wrapping. The
popup shows the title and `capsule_id` separately instead of concatenating them
into one elided line.

## Restored preserved-save selection

For **Direct-Wine**, the GUI scans:

```text
<COLLECTION>/03_PERSISTENT_STATE/<capsule_id>/save-sets/index.json
```

The selector lists registered save sets and resolves a portable state-backup
directory from the save-set `source` object, using the first valid key among:

```text
state_backup
accepted_state
backup_path
```

Only relative paths contained by the collection are accepted. Absolute paths,
symlinks, missing directories, and escaping paths are rejected. A custom
Direct-Wine backup directory may still be selected manually.

The current core compose contract exposes `--state-backup` only for
Direct-Wine. The save selector is therefore deliberately hidden for Bottles
and UMU; the GUI does not claim unsupported restoration semantics.

Example sanitized index:

```json
{
  "schema": 1,
  "save_sets": [
    {
      "save_set_id": "main-progress",
      "display_name": "Main progress",
      "captured_at": "2026-08-04T18:00:00Z",
      "source": {
        "state_backup": "03_PERSISTENT_STATE/example-game/backups/main"
      }
    }
  ]
}
```

## Installation

A networked development installation:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
ogv-gui
```

Reference dependency version:

```text
PySide6 6.11.1
```

The project metadata accepts PySide6 6.8 through the current Qt 6 series. For a
reproducible offline package, archive the exact platform wheels and their
hashes separately; this source ZIP does not contain third-party wheels.

## Development

```bash
./scripts/check-host.sh
./scripts/test.sh
./scripts/check-core-contract.sh ../offline-game-vault
./scripts/run-dev.sh
```

The headless tests validate the domain layer without requiring Qt. When
PySide6 is installed, the suite also runs an offscreen Qt smoke test. Actual
rendering must still be tested in a graphical session.

## Appearance and personalization

The application uses the active Qt platform style and palette. It does not
force Fusion, Adwaita, Breeze, dark mode, or custom colors.

Optional local overrides:

```text
OGV_QT_STYLE=<Qt style name>
OGV_QT_STYLESHEET=<regular .qss file>
```

These affect presentation only and are not written to the Vault.

## Safety boundaries

The GUI does not:

- download runners or runtimes;
- use a system Wine or Proton fallback;
- modify the immutable Vault;
- reconstruct backend launch commands after materialization;
- interpret acceptance evidence as permission;
- apply Steamless, Steamworks emulation, anti-cheat changes, or DRM changes.

A successful materialization proves assembly and structural verification. It
does not prove gameplay, saves, DLC, video, audio, controller support,
isolation, normal shutdown, or clean restoration.

## Privacy

Preferences are stored under the XDG configuration directory. Minimized
operation receipts are stored under the XDG state directory. Receipts do not
include raw core JSON, command output, or the state-backup path.

The screenshots used as design references are intentionally not included in
this source tree because they contain host-specific paths.

## License

Application source: Apache License 2.0.

PySide6/Qt for Python is a separate third-party dependency distributed under
its own open-source or commercial licensing terms. See `docs/THIRD_PARTY.md`.
