# Release notes — 0.5.0a4

## Bottles external materialization

- Requires an explicit destination for Bottles, matching the user-facing
  destination contract already used by Direct-Wine and UMU.
- Displays and returns the external materialization root instead of deriving a
  private Bottles directory.
- Keeps Bottles managed-path discovery only for registration safety.
- Recalculates the suggested bottle name when the selected game changes until
  the user deliberately edits the field.
- Preserves a deliberate manual bottle name across later selection changes.
- Continues to execute only core-generated `JUGAR.sh`, `VERIFICAR.sh`, and
  `DESINSTALAR.sh` operations.

## Persistent-state timeline

- Discovers every collection-contained `state-backup.json` for the selected
  capsule and verifies each candidate through the authoritative core.
- Displays the receipt `created_at` timestamp in the host's local timezone.
- Sorts verified backups from newest to oldest; undated receipts appear last.
- Keeps the technical backup ID as secondary information instead of using it
  as the user's primary label.
- Distinguishes backups containing saved-game payloads from identity-only and
  empty state.
- Displays present and missing item counts without treating `verified=true` as
  proof that a saved game exists.
- Retains save-set names as optional provenance when a single save set points
  to the verified backup.

## Core compatibility

- Requires `offline-game-vault` 0.12.2 or newer.
- Uses compatible historical-state verification and backend-neutral
  `compose --state-backup` for Bottles, Direct-Wine, and UMU.

## Safety

- Does not mutate the Vault.
- Rejects linked, irregular, escaping, or core-invalid backup candidates.
- Reads receipt metadata only after the core verifies the backup.
- A successful materialization remains separate from gameplay, save loading,
  DLC, isolation, normal shutdown, and clean-restoration acceptance.
