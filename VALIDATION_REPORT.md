# Validation report — PySide6 source tree 0.5.0a4

Generated: 2026-08-05.

## Automated in the delivered source

- Python syntax across `src`, `tests`, and `tools`;
- headless domain tests;
- exact backend-neutral compose command tests;
- source-profile Auto/default contract tests;
- recursive state-backup discovery and core verification tests;
- receipt-date parsing and newest-first ordering tests;
- save-bearing versus identity-only state classification tests;
- service path and generated-operation safety tests;
- save-set containment and symlink tests;
- catalog state-free profile tests;
- dynamic version consistency;
- static PySide6/Qt and no-GTK contract tests;
- shell-script syntax;
- source SHA-256 manifest generation and verification;
- privacy-pattern and symlink audit.

## Core contract basis

```text
offline-game-vault >= 0.12.2
compose --backend bottles|direct-wine|umu
        --state-backup <backup>
```

The core remains authoritative for backup verification, historical-definition
compatibility, backend state-root resolution, pre-restore snapshotting,
restoration, evidence, and atomic publication.

## Verified outside the synthetic GUI tests

- A historical Sekiro backup materialized through UMU with core 0.12.2 and
  loaded its preserved save.

## Not validated by this source-tree run

- actual rendering in every supported graphical session;
- operation against other private collections;
- save loading for other titles;
- DLC content loading;
- video, audio, controller, or hotplug behavior;
- external network isolation;
- normal shutdown;
- relocation and clean restoration.

These limitations must not be converted into guarantees.
