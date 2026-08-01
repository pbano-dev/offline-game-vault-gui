# Development

## Requirements

- Python 3.11 or newer;
- GTK4 and PyGObject;
- libadwaita;
- Bubblewrap and Flatpak where the selected backend requires them;
- `offline-game-vault` 0.11.3 or newer;
- an existing Offline Game Vault collection.

## Source checkouts

For development, keep the repositories as siblings:

```text
<WORKSPACE>/
├── offline-game-vault/
└── offline-game-vault-gui/
```

The GUI prefers the sibling core over an older `ogv` in `PATH`. An explicit
checkout may also be selected with:

```bash
export OGV_SOURCE_ROOT=<WORKSPACE>/offline-game-vault
```

## Run

```bash
export OGV_COLLECTION_ROOT=<VAULT>
./scripts/run-dev.sh
```

For Bottles:

```bash
```

## Validate

```bash
./scripts/check-host.sh
./scripts/test.sh
git diff --check
```

The test suite must not access the Internet. Synthetic fixtures build tiny
local game, runner, and UMU objects and exercise the same core command contract
used by the GUI.

## Packaging

```bash
./scripts/package-source.sh dist
```

Restore executable bits after transferring through ZIP before running scripts.
