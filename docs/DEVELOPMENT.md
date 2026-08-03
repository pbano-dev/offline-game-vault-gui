# Development

## Headless checks

```text
./scripts/test.sh
```

The test suite requires only Python 3.11 or newer. PyGObject is imported lazily
so CI can validate the controller without a display server.

## Running the application

```text
./scripts/check-host.sh
./scripts/run-dev.sh
```

## Core checkout

For development against the unmerged core branch:

```text
export OGV_SOURCE_ROOT=/path/to/offline-game-vault
```

The checkout must contain `src/offline_game_vault/cli.py` and report core
version 0.11.4 or newer.

## Release archive

```text
./scripts/package-source.sh
```

The script regenerates `SOURCE_MANIFEST_SHA256.txt`, creates a ZIP with one
top-level directory, extracts it again, verifies the manifest, and reruns the
headless suite.
