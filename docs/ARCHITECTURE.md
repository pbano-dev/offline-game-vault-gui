# Architecture

## Authority

The immutable Vault and `offline-game-vault` core remain authoritative. The GUI
is a selector and job controller; it does not reinterpret object integrity,
extract archives itself, or grant functional acceptance.

```text
capsule + preserved runner + automatically resolved shared runtime
                            |
                            v
               user-requested selection
                            |
                            v
          ogv materialize-experimental
                            |
                            v
              writable experimental derivative
```

## Descriptive contracts

Capsule profiles, host contracts, acceptance reports, and receipts describe
known configurations and historical results. They do not authorize or prohibit
a user-requested experimental materialization.

The GUI therefore exposes Bottles, Direct-Wine, and UMU for every discovered
capsule. It may pass a source-profile override, but the default is deterministic
selection by the core. Missing exact backend profiles are synthesized by core
0.11.3 from compatible neutral Linux layouts.

## Material blockers

The GUI blocks only when a required piece or safe operation is impossible:

- incompatible core;
- missing or corrupt capsule/object;
- no preserved runner compatible with the backend;
- no reusable shared UMU runtime object;
- unsafe or occupied destination;
- missing managed Bottles directory.

Status labels never form part of this gate.

## Runner catalog

The GUI does not maintain an independent authoritative runner scanner. It
consumes the machine-readable result of:

```text
ogv list-preserved-runners --json
```

The core has already checked canonical object location, size, SHA-256, archive
layout, Wine/Wineserver paths, and Proton entrypoint where applicable.

## Shared UMU runtime resolution

UMU combines:

1. the selected preserved Proton runner;
2. one reusable UMU/Python/Steam Linux Runtime object resolved by the core.

The GUI does not list or select another game's capsule/profile as a backend.
The core accepts only runtime objects explicitly marked shared and identifies
them by content digest. Source capsule/profile fields are provenance only.

## Operations

Materialization uses:

```text
ogv materialize-experimental
```

Every backend must then publish at the materialization root:

```text
JUGAR.sh
VERIFICAR.sh
DESINSTALAR.sh
```

The GUI calls those scripts for first play, later play, verification, and
removal. It does not reconstruct backend commands from the capsule or receipt.
The backend receipt remains authoritative and each script validates it before
acting.

The GUI may write a local convenience selection receipt inside an output. Core
receipts and the generated operational scripts remain authoritative.

## Core resolution

All backends share one resolved core process. The GUI validates its command
surface before loading preserved runners. A configured or sibling source
checkout precedes `PATH`, avoiding mixed core versions during development.
