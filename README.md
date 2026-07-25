# OfflineGameVault GUI

OfflineGameVault GUI is a GTK4/libadwaita desktop application for browsing an
OfflineGameVault collection and creating derived game materializations without
modifying the immutable vault.

## Capabilities

- Reads canonical capsules from an OfflineGameVault collection.
- Supports candidate and verified profiles.
- Lets the operator select a backend, profile, preserved runner, save set, and
  local destination.
- Supports multi-item save sets as one atomic selection.
- Materializes through:
  - Bottles;
  - Direct-Wine;
  - candidate Windows exports;
  - base-only extraction.
- Keeps the collection read-only while materialization workers are running.
- Records selection and materialization receipts.
- Checks critical collection seals before and after operations.
- Never downloads runners or runtime components.

## Current status

This repository is an alpha-quality development snapshot.

Verified acceptance evidence currently covers Bottles materialization for
ELDEN RING NIGHTREIGN with both a selected multi-item save set and a clean
no-save baseline. Direct-Wine remains a candidate workflow pending independent
functional acceptance after the layout correction included in this release.
Native Windows export has not been functionally tested.

A successful structural materialization is not equivalent to verified gameplay.
Acceptance does not transfer between runners, backends, save selections, or
hosts.

## Requirements

Runtime requirements:

- Python 3.11 or newer;
- GTK4 Python bindings;
- libadwaita Python bindings;
- a compatible `offline-game-vault` checkout or installation;
- Bubblewrap for materialization workers;
- Bottles Flatpak for the Bottles backend;
- preserved runner objects in the collection for Wine-based backends.

The automated unit tests use the Python standard library and do not require a
running GTK session.

## Development setup

Create an isolated Python environment:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

GTK and libadwaita bindings are normally installed through the host package
manager rather than PyPI.

Run the application:

```bash
./scripts/run-dev.sh
```

Run the complete repository validation:

```bash
./scripts/test.sh
```

Inspect host integration:

```bash
./scripts/check-host.sh
```

Create a clean source archive:

```bash
./scripts/package-source.sh dist
```

## Repository layout

```text
.github/    continuous-integration workflow
data/       desktop integration files
docs/       architecture, security, development, host, and acceptance documents
scripts/    development, validation, packaging, and runtime helper scripts
src/        Python package
tests/      automated tests and synthetic fixtures
```

## Safety and privacy

The vault remains the source of truth. Materializations are derived outputs.
The application does not modify DRM or anti-cheat components; it operates on
capsules and objects already registered in the operator's private collection.

Do not commit raw Wine, Bottles, DXVK, VKD3D, or build logs. They can contain
absolute host paths, usernames, hostnames, UIDs, UUIDs, and session identifiers.
Run `./scripts/audit-privacy.sh` before publishing a source archive.

The test suite contains clearly synthetic host paths to exercise path
sanitization. They do not identify a real user or host.

## Documentation

- `docs/ARCHITECTURE.md`
- `docs/SECURITY_MODEL.md`
- `docs/ACCEPTANCE.md`
- `docs/DEVELOPMENT.md`
- `docs/FEDORA_SILVERBLUE.md`
- `RELEASE_NOTES.md`

## License

Apache License 2.0. See `LICENSE`.
