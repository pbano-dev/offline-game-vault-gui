# Validation report — PySide6 replacement source tree

Generated on 2026-08-04.

## Automated validation

The delivered ZIP is checked for:

- Python syntax across `src`, `tests`, and `tools`;
- non-Qt unit tests for catalog, core command construction, service safety,
  save-set scanning, configuration, and data models;
- absence of GTK/libadwaita imports;
- presence of PySide6 Qt Widgets imports;
- exact source-manifest verification;
- absence of generated Python artifacts;
- public privacy patterns and symlinks;
- executable shell-script syntax;
- clean extraction followed by a second validation pass.

## Contract basis

The preserved core interface remains:

```text
discover-bottles-path
list-preserved-runners
list-shared-umu-runtimes
compose
```

Post-materialization operations use only:

```text
JUGAR.sh
VERIFICAR.sh
DESINSTALAR.sh
```

## Not validated here

The build environment does not contain PySide6 or a display server. Therefore
this report does not claim:

- actual Qt widget rendering;
- interaction under Plasma, GNOME, X11, or Wayland;
- Bottles discovery on the user's host;
- materialization against a private Vault;
- save loading inside a game;
- DLC, video, audio, input, isolation, shutdown, or restoration acceptance.

Those remain host-level acceptance tests.
