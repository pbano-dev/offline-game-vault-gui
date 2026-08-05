# Qt frontend architecture

## Boundary

```text
app.py (PySide6/Qt Widgets)
    -> service.py
    -> core.py
    -> offline-game-vault CLI 0.12.0+
```

`app.py` owns presentation, dialogs, background workers, and temporary UI
selection. `service.py` owns local path safety, private minimized receipts, and
generated-operation execution. `core.py` owns the strict public
subprocess/JSON client. The core repository owns preservation and restoration
policy.

## Presentation

Qt Widgets are used directly. No QML, Qt Quick, Kirigami, GTK, libadwaita,
PyGObject, or GLib compatibility layer is retained.

`RichComboBox` and `RichItemDelegate` render full wrapped labels. Domain
objects are stored as item payloads; technical identifiers are never parsed
back from display text.

## Backend-neutral state

`save_sets.py` reads optional private collection metadata. A selected save set
is converted to the common `state_backup` request field only after containment,
type, existence, and symlink checks.

The same field is supported for Bottles, Direct-Wine, and UMU. The GUI does not
derive a prefix or save root. Core 0.12 verifies the backup, resolves the
effective backend state root, restores in staging, records evidence, and
publishes atomically.

The save-set ID is local provenance. It does not modify the operational capsule
or authorize restoration.

## Threading

Core subprocess operations run through `QThreadPool` and `QRunnable`.
Presentation updates return through Qt signals to the GUI thread.

## Generated operations

After composition, the GUI invokes only regular executable files generated in
the materialization root:

```text
JUGAR.sh
VERIFICAR.sh
DESINSTALAR.sh
```

Symlinks, missing files, non-regular files, non-executable files, and resolved
paths outside the materialization root are rejected.

## Persistence

Preferences use XDG config. Local minimized receipts use XDG state. Neither is
part of the immutable Vault.
