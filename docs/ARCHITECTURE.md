# Architecture

## Boundary

The GUI is a controller. The core remains authoritative for inventory,
integrity, compatibility, extraction, materialization, runtime isolation, and
receipts.

```text
GTK view
  -> CompositionService
    -> CapsuleCatalog
    -> CoreClient
      -> offline-game-vault 0.11.4
```

## State-free model

`GameRecord` contains source profiles parsed from the capsule. A
`SourceProfile` records only an identifier, platform, adapter, and playable
backend. It has no maturity, acceptance, publication, or ownership state.

`RunnerRecord` is created only from the core runner catalog.
`ComponentSet` is created only from the core UMU diagnostic catalog. The GUI
does not infer either from capsule labels or host installations.

## Composition

A `CompositionRequest` names:

- the collection;
- source capsule;
- requested backend;
- preserved runner;
- optional source-profile override;
- destination or Bottles derivative name;
- optional Direct-Wine state backup;
- optional game arguments for Direct-Wine or UMU.

The core synthesizes the operational profile and leaves the source capsule
unchanged.

## Post-materialization operations

The GUI records the destination returned by the core. Play, Verify, and Remove
resolve one of the three generated root scripts and reject symlinks,
non-regular files, non-executable files, and paths outside that exact
materialization.

The GUI does not duplicate backend launch logic.

Backend-specific removal confirmations or export options are passed as argument arrays to the generated `DESINSTALAR.sh`; the GUI does not interpret them as acceptance state.
