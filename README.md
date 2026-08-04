# Offline Game Vault GUI 0.4.1

GTK4/libadwaita controller for requesting writable Bottles, Direct-Wine, and
UMU/Proton compositions from pieces already preserved in an Offline Game
Vault.

This tree targets `offline-game-vault` **0.11.4** on
`refactor/state-free-components`.

## Operating model

The Vault stores pieces and facts, not opinions about maturity.

- Profiles are source-layout recipes.
- Acceptance reports are separate historical evidence.
- Wine/Proton runners, the UMU/Python backend, and Steam Linux Runtime objects
  are reusable global components.
- The core resolves concrete objects and blocks only on technical facts:
  missing or corrupt objects, unsafe archives or paths, incompatible
  dependencies, occupied targets, and an incompatible core.
- A successful materialization proves structural assembly and verification.
  It does not prove gameplay, save loading, DLC, controller behavior,
  isolation, normal shutdown, or clean restoration.

The GUI does not expose `verified`, `candidate`, `not_tested`, `experimental`,
`accepted`, or similar labels as profile or component maturity.

## Supported operations

The GUI can:

1. discover capsules from `<COLLECTION>/02_CAPSULES/*/capsule.json`;
2. list preserved runners through the core;
3. show resolved UMU component sets for diagnostics;
4. request Bottles, Direct-Wine, or UMU compositions;
5. invoke the generated root operations, including backend-specific Remove arguments:
   - `JUGAR.sh`;
   - `VERIFICAR.sh`;
   - `DESINSTALAR.sh`.

It never reconstructs a second launch command and never downloads a runner,
runtime, or backend.

## Core discovery

Resolution order:

1. `OGV_EXECUTABLE`;
2. `OGV_SOURCE_ROOT`;
3. a sibling `offline-game-vault` checkout;
4. `ogv` in `PATH`.

Runner identifiers are consumed exactly as returned by the core. The GUI
accepts the core portable identifier contract, including case-sensitive IDs
such as `Proton-9.0-203`; it does not normalize or rewrite them.

The selected core must be version 0.11.4 or newer and must provide:

```text
discover-bottles-path
list-preserved-runners
list-shared-umu-runtimes
compose
```

## Host requirements

Runtime GUI:

- Python 3.11 or newer;
- GTK 4;
- libadwaita 1;
- PyGObject;
- a compatible Offline Game Vault core.

On Fedora Silverblue:

```text
sudo rpm-ostree install python3-gobject gtk4 libadwaita
```

After reboot, run from a source checkout:

```text
./scripts/check-host.sh
./scripts/test.sh
./scripts/run-dev.sh
```

## Environment

Optional variables:

```text
OGV_COLLECTION_ROOT
OGV_DESTINATION_PARENT
OGV_EXECUTABLE
OGV_SOURCE_ROOT
```

The GUI stores local preferences and a minimized operation receipt below the
user's XDG config/state directories. Receipts omit raw core result objects,
command output, and argument values. They remain private local files and must
be sanitized before publication. The GUI does not write policy into the Vault.

## Replacing the 0.3.3 source tree

This archive is a complete repository source tree, not an overlay. Replace the
old branch contents while preserving `.git`. Do not leave the retired
`experimental_*`, `neutral_profiles`, runner-override, or old UMU bridge
modules in the branch. See `REPOSITORY_REPLACEMENT.md`.

## Validation

Run:

```text
./scripts/test.sh
```

The suite is headless and uses a synthetic core executable to test command
construction and JSON contracts. GTK import and a private Vault are separate
host validation steps.

## License

Apache License 2.0.
