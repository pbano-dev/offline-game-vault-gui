# Development guide

## Scope

OfflineGameVault GUI is an orchestration layer. The `offline-game-vault` core,
capsule files, object digests, and receipts remain authoritative. GUI code must
not silently redefine facts from those sources.

## Source layout

```text
src/offline_game_vault_gui/
    GTK application and orchestration modules
scripts/
    host checks, core wrappers, state bridge, tests, and packaging
tests/
    standard-library unit tests with synthetic vault fixtures
data/
    desktop integration
docs/
    design and acceptance documentation
```

## Local environment

Python 3.11 or newer is required. Install GTK4, libadwaita, and PyGObject through
the host package manager. Then install this project in editable mode:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

A compatible `offline-game-vault` checkout can be selected with
`OGV_SOURCE_ROOT`. An installed command can be selected with `OGV_EXECUTABLE`.

## Tests

Run all repository checks:

```bash
./scripts/test.sh
```

The command performs:

1. state-bridge executable and help checks;
2. 76 unit tests;
3. shell syntax validation;
4. Python AST parsing;
5. repository privacy auditing.

Tests use temporary directories and synthetic identifiers. They must not depend
on a developer's actual home directory, host name, vault, runner inventory, or
network access.

## Functional acceptance

Automated tests establish code-level and structural behavior. They do not prove
that a game works. Functional acceptance must be recorded separately for every
combination of:

```text
capsule
profile
backend
runner
save selection
host contract
```

Use `docs/ACCEPTANCE.md` and retain sanitized evidence.

## Translation and user-visible text

Repository documentation, GUI labels, diagnostics, generated launcher text,
comments intended for contributors, and release notes are maintained in
English. Machine contract keys and upstream command names must not be translated.

## Privacy

Run:

```bash
./scripts/audit-privacy.sh
```

The audit checks text, raw-log names, compiled files, and symbolic links. It is
not a substitute for review. Binary additions require a separate strings and
provenance audit before publication.

Optional project-specific markers can be supplied without writing them into the
repository:

```bash
OGV_PRIVATE_MARKERS=$'marker-one\nmarker-two' ./scripts/audit-privacy.sh
```

## Source release

Create a clean archive with:

```bash
SOURCE_DATE_EPOCH=0 ./scripts/package-source.sh dist
```

The packager runs the full validation first and excludes Git metadata, virtual
environments, caches, compiled Python files, logs, and previous archives.
Compute and publish the archive SHA-256 separately.

## Contribution rules

- Preserve original objects and read-only vault semantics.
- Reject unsafe paths instead of normalizing them silently.
- Do not download missing components.
- Keep preservation and network isolation as separate concerns.
- Do not transfer acceptance between backends or runners.
- Add a regression test for every fixed defect.
- Keep release history in `RELEASE_NOTES.md` only.
