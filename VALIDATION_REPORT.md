# Validation report

Generated for GUI 0.4.1 on 2026-08-03.

## Automated checks included in this source tree

- Python syntax compilation for `src`, `tests`, and `tools`;
- unit tests for capsule discovery and rejection of retired profile fields;
- synthetic-core tests for version probing and all required JSON commands;
- exact core runner-identifier compatibility, including uppercase preserved
  identifiers such as `Proton-9.0-203`;
- exact argument tests for Bottles, Direct-Wine, and UMU composition;
- post-materialization script path and symlink guards;
- repository version consistency;
- source-tree semantic scan;
- privacy scan for common host-path leaks;
- archive manifest verification;
- 26 headless unit and contract tests;
- local wheel build and isolated installation without dependency downloads;
- clean ZIP extraction and a second full test run.

## Optional real-core contract check

Run:

```text
./scripts/check-core-contract.sh ../offline-game-vault
```

This probes an actual core checkout, verifies the minimum version, and checks
that every required public command is available. It does not materialize a
private Vault or claim per-game functional acceptance.

## Boundaries

The automated suite does not claim:

- a GTK window was rendered on every target host;
- a private Vault was materialized;
- Bottles Flatpak was available;
- a real game, save, DLC, or controller was tested;
- network isolation or clean restoration was functionally accepted.

Those remain host and per-game acceptance tests.
