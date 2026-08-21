# Offline Game Vault GUI — PySide6/Qt Widgets 0.5.0a5

Complete PySide6/Qt Widgets frontend for
[`offline-game-vault`](https://github.com/pbano-dev/offline-game-vault)
0.19.5 or newer.

This source tree replaces the GTK4/libadwaita presentation layer. It does not
replace or duplicate core preservation policy.

## Authority boundary

The core remains authoritative for:

- immutable-object verification;
- runner and UMU component selection;
- Bottles, Direct-Wine, and UMU composition;
- backend state-root resolution;
- verified persistent-state restoration;
- pre-restore snapshots and restoration evidence;
- atomic publication;
- generated `JUGAR.sh`, `VERIFICAR.sh`, and `DESINSTALAR.sh` operations.

The GUI is a thin subprocess/JSON client:

```text
capsule.json
    -> catalog.py
    -> service.py
    -> core.py
    -> offline-game-vault CLI
```

The GUI never derives prefix paths, save paths, AppIDs, DLC ownership, runner
fallbacks, or backend launch commands.

For Bottles, the destination selected in the GUI is the authoritative external
materialization root. The GUI passes it to the core and later invokes only the
generated root scripts. The managed Bottles path is displayed for diagnostic
registration purposes; it is not presented as the materialization destination.

The suggested bottle name is recalculated when the selected game changes until
the user edits the name manually. A deliberate manual name is then preserved
across selection changes.

## Core 0.19.5 state contract

Persistent state is an explicit composition choice for every backend:

```text
compose \
  --backend bottles|direct-wine|umu \
  --state-backup <VERIFIED_BACKUP>

compose \
  --backend bottles|direct-wine|umu \
  --no-state
```

`--fresh-start` is the normal **Start a new game** intent: it omits
restorable saved-game state while preserving backend-required initial
configuration. `--state-backup` restores preserved state. `--no-state` is the
stronger explicit operator control: it skips all state, including backend
configuration declared as mandatory. These modes are mutually exclusive.

For a preserved UMU-native profile, the capsule may also declare
`umu.state_archives`. Archives with policy `always` are injected by the core
when state is provisioned and are not user choices. Archives with policy
`selectable` appear in **Initial game state** and the GUI sends their exact
`--save-id`. Choosing an UMU-native save also pins the source profile that
declares it. Choosing **Start a new game** sends `--fresh-start`. For a preserved
UMU-native source, the core still applies `always` archives and selects no
`selectable` save. The GUI does not interpret those backend policies itself.

The GUI can obtain a backend-neutral state-backup directory from either:

- a registered private save set under
  `03_PERSISTENT_STATE/<capsule_id>/save-sets/index.json`; or
- a manually selected directory.

The source-layout selector defaults to **Auto (recommended)**. In this mode
the GUI omits `--source-profile` and the core chooses the best technically
compatible source contract for the selected backend. Profile names such as
`linux-bottles-flatpak` are not compatibility guarantees; the referenced host
contract is authoritative.

The state selector lists only backups that contain `state-backup.json` and
pass the core's `verify-state-backup` command. Save-set metadata can provide a
display name and provenance, but it is not itself a restorable backup.

Every verified receipt is presented by its `created_at` timestamp, newest
first. The timestamp is converted to the host's local timezone for display.
The technical backup ID remains visible as secondary information. Backups
whose verified payload contains save-kind items are distinguished from
identity-only state and empty state, so a valid identity snapshot is not
misrepresented as a saved game.

The same selector remains visible for Bottles, Direct-Wine, and UMU. Its
first entry is **Start a new game**, which sends `--no-state` explicitly.
That choice remains valid when the capsule declares preservable state and when
verified backups already exist. Selecting a preserved backup instead sends
`--state-backup`.

Only collection-contained, relative save-set source paths are resolved.
Absolute paths, path escapes, symlink traversal, missing directories, and
non-directories are rejected.

## Functional scope

The frontend provides:

- collection-root and default-target selection;
- explicit core-checkout selection and compatibility probing;
- game, backend, source-profile, and preserved-runner selection;
- backend-neutral preserved save-set and backup selection;
- Bottles managed-path discovery for rebuildable registration;
- external target selection for Bottles, Direct-Wine, and UMU;
- UMU component-set diagnostics;
- additional Direct-Wine/UMU play arguments;
- generated Remove arguments;
- Materialize, Materialize & Play, Verify, Play, and Remove;
- private minimized operation receipts;
- background workers so long core operations do not block the interface;
- wrapped game titles and secondary identifiers without ellipsis.

## Installation

Networked development installation:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
ogv-gui
```

Reference dependency:

```text
PySide6 6.11.1
```

The project accepts PySide6 6.8 through the current Qt 6 series. For a
reproducible offline package, archive the exact platform wheels, hashes, and
license notices separately. This source ZIP contains no third-party wheels.

## Development and validation

```bash
./scripts/check-host.sh
./scripts/test.sh
./scripts/check-core-contract.sh ../offline-game-vault
./scripts/audit-privacy.sh
./scripts/run-dev.sh
```

`test.sh` always runs headless domain and contract tests. When PySide6 is
installed, it also runs the offscreen Qt smoke test.

## Appearance

The active Qt platform style and palette are authoritative. The application
does not force Fusion, Adwaita, Breeze, dark mode, or custom colors.

Optional local overrides:

```text
OGV_QT_STYLE=<Qt style name>
OGV_QT_STYLESHEET=<regular .qss file>
```

These affect presentation only and are never written to the Vault.

## Safety boundaries

The GUI does not:

- download runners, runtimes, or game data;
- fall back to system Wine or Proton;
- mutate immutable Vault objects;
- reconstruct launch commands after materialization;
- treat acceptance evidence as authorization;
- apply Steamless, Steamworks emulation, anti-cheat changes, or DRM changes;
- claim that materialization proves gameplay acceptance.

A successful composition demonstrates assembly and structural verification.
It does not prove save loading, DLC, video, audio, controller support, network
isolation, normal shutdown, relocation, or clean restoration. Those remain
per-title acceptance tests.

## Privacy

Preferences are stored under the XDG configuration directory. Minimized local
operation receipts are stored under the XDG state directory.

Receipts record identifiers and boolean selection facts. They do not record:

- the state-backup path;
- the materialization destination;
- raw core JSON;
- command output;
- usernames, hostnames, UIDs, UUIDs, or private collection inventories.

## License

Application source: Apache License 2.0.

PySide6/Qt for Python is a separate third-party dependency distributed under
its own licensing terms. See `docs/THIRD_PARTY.md`.
