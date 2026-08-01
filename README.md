# Offline Game Vault GUI 0.3.3

GTK4/libadwaita controller for assembling and testing writable game variants
from pieces already preserved inside an Offline Game Vault.

The GUI never treats acceptance status as permission. If a capsule and the
required preserved pieces exist, the user may request an experimental variant
for:

- Bottles;
- Direct-Wine;
- UMU/Proton.

Windows-native materialization is outside this release.

## Operating rule

For every discovered game the GUI presents the three Linux backends. It then
lists only runners returned by the core command:

```text
ogv list-preserved-runners
```

A runner is offered when the updated core reports structural compatibility
with the selected backend. `verified`, `candidate`, `not_tested`,
`experimental`, and `unavailable` remain evidence labels; none of them blocks
materialization.

When the exact backend profile does not exist, core 0.11.3 synthesizes an
experimental private profile from a compatible neutral Linux source. The
source capsule is not rewritten.

## Materialize and test

The selection flow is:

1. game;
2. backend;
3. optional source-profile override;
4. preserved runner;
5. optional Direct-Wine state backup;
6. output target;
7. Materialize, Materialize & Play, Verify, Play, or Remove.

Every successful materialization must contain these executable root-level
operations:

```text
JUGAR.sh
VERIFICAR.sh
DESINSTALAR.sh
```

`Materialize & Play` first asks the core to materialize and then invokes the
generated `JUGAR.sh`. Play, Verify, and Remove likewise use the scripts
published by that exact backend; the GUI does not reconstruct a second launch
path.

A successful materialization proves that the declared pieces assembled and
verified. It does not prove gameplay, saves, DLC, video, audio, controller
support, isolation, normal shutdown, or restoration.

## Preserved pieces only

The GUI does not:

- download runners or runtimes;
- search the Internet;
- use a system Wine or Proton as a fallback;
- reuse an arbitrary runner already installed in Bottles;
- modify DRM, SteamStub, Steamworks, or anti-cheat components.

Bottles, Direct-Wine, and UMU receive runner IDs from the Vault catalog.
For UMU, the core automatically resolves a reusable shared object containing
the preserved UMU, portable Python, and Steam Linux Runtime pieces. The GUI
never asks the user to select another game's profile as a backend.

## Core requirement

A compatible `offline-game-vault` **0.11.3 or newer** is required. At startup
the GUI verifies all commands needed for materialization, verification,
execution, and removal.

Resolution order:

1. `OGV_EXECUTABLE`;
2. `OGV_SOURCE_ROOT`;
3. a sibling `offline-game-vault` checkout;
4. `ogv` in `PATH`.

A source checkout is preferred over an installed executable during development,
preventing an old system-wide `ogv` from being selected silently. The GUI also
provides **Select checkout…** for the current session.

## Configuration

Optional environment variables:

```text
OGV_COLLECTION_ROOT
OGV_DESTINATION_PARENT
OGV_EXECUTABLE
OGV_SOURCE_ROOT
```

For Bottles, the active managed directory is discovered through
`bottles-cli info bottles-path` and displayed read-only. It cannot be replaced
with an arbitrary destination. The selected runner is installed from its
immutable Vault object by the core; large prematerialization trees are created
inside the managed directory, never in the host `/tmp`.

## Development

```bash
./scripts/check-host.sh
./scripts/test.sh
./scripts/run-dev.sh
```

The test suite includes command-contract tests and an end-to-end synthetic
integration against core 0.11.3 for Bottles, Direct-Wine, and UMU.

## Safety boundary

Only material failures block an operation:

- missing or corrupt object;
- missing or corrupt runner;
- backend-incompatible runner;
- absent reusable shared UMU runtime object;
- unsafe path or symlink;
- occupied target;
- incompatible or missing core.

Receipts describe what was assembled and whether play completed. They do not
authorize future operations or transfer functional acceptance.

## License

Apache License 2.0.
