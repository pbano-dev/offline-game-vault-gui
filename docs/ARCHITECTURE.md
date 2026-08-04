# Qt frontend architecture

## Boundary

```text
app.py (PySide6/Qt Widgets)
    -> service.py
    -> core.py
    -> offline-game-vault CLI 0.11.4+
```

`app.py` owns presentation, dialogs, background workers, and temporary UI
selection. `service.py` owns local safety checks and generated-operation
execution. `core.py` owns the public subprocess/JSON contract. The core
repository owns composition policy.

## UI model

Qt Widgets are used directly. No QML, Qt Quick, Kirigami, GTK, libadwaita,
PyGObject, or GLib compatibility layer is retained.

`RichComboBox` and `RichItemDelegate` render complete wrapped labels. Domain
objects are stored as Qt item payloads; the GUI does not derive technical IDs
from display strings.

## Save selection

`save_sets.py` reads optional private collection metadata. A selected save set
is converted to the existing Direct-Wine `state_backup` request field only
after containment, type, and symlink checks.

The save-set ID is provenance for the local GUI receipt. It is not a core
authorization field and does not alter the source capsule.

## Threading

Core subprocess operations run through `QThreadPool` and `QRunnable`.
Presentation changes return through Qt signals to the GUI thread.

## Styling

The host Qt style and palette are authoritative. Local QSS is opt-in and never
stored in the Vault.
