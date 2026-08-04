# Release notes — 0.5.0a1

## Presentation layer

- Replaced GTK4, libadwaita, PyGObject, and GLib with PySide6 Qt Widgets.
- Kept the state-free core boundary unchanged.
- Added native Qt background workers.
- Added adaptive `QFormLayout` forms and platform-native styling.
- Added complete, wrapped game-title rendering in both the selected value and
  popup list.
- Added optional Qt style and QSS overrides.

## Persistent state

- Restored preserved save-set discovery and selection.
- Kept manual Direct-Wine state-backup selection.
- Enforced collection-contained relative paths for save-set sources.
- Passed the resolved directory through the existing core
  `--state-backup` contract.
- Recorded only the save-set ID and a boolean selection fact in local receipts.

## Compatibility

- Requires `offline-game-vault >= 0.11.4`.
- Requires Python 3.11 through 3.14.
- Requires PySide6 6.8 or newer within Qt 6.
- Reference environment: PySide6 6.11.1.

## Limits

- Rendering has not been validated in this build environment because PySide6
  is not installed there.
- Bottles, game payloads, private saves, and a private Vault are not included.
- Functional per-game acceptance remains pending on the user's host.
