# Repository replacement instructions — PySide6/Qt Widgets 0.5.0a1

This ZIP is a complete source tree for a dedicated test branch. It is not an
overlay and must not be copied over a dirty worktree.

## Recommended procedure

1. Start from the current GUI `main`.
2. Create a new branch.
3. Preserve only the repository's `.git` directory.
4. Replace the tracked source tree with the contents of this archive.
5. Keep private collection paths, screenshots, logs, and credentials outside
   the repository.
6. Install the exact PySide6 dependency in an isolated environment.
7. Run the checks below before committing.

```bash
./scripts/check-host.sh
./scripts/test.sh
./scripts/check-core-contract.sh ../offline-game-vault
QT_QPA_PLATFORM=offscreen python3 -B -m unittest     tests.test_qt_smoke -v
```

## Migration boundary

The replacement removes GTK4, libadwaita, PyGObject, and GLib presentation
code. It does not change the core CLI contract, capsule format, Vault layout,
runner identifiers, generated root operations, or acceptance semantics.

The source ZIP does not contain PySide6 wheels. Archive exact platform wheels,
hashes, and license notices separately before treating a deployment as
reproducible or offline.
