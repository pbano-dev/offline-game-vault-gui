# Security model

## Trusted authority

The selected `offline-game-vault` core is authoritative. The GUI requires
version 0.11.4 or newer and probes each command it depends on.

## Path rules

- Collection and capsule paths must resolve beneath the selected collection.
- Direct-Wine and UMU destinations must not exist.
- A destination must not be inside the collection.
- Generated operation scripts must be regular executable files, not symlinks,
  and must resolve directly beneath the materialization root.
- The GUI never follows a receipt-supplied operation path.

## Process rules

Commands are executed as argument arrays without a shell. Output is captured as
UTF-8 with replacement for invalid bytes. Error messages are bounded before
display.

## Network and downloads

The GUI does not download anything and has no networking code. It does not
substitute a host Wine, Proton, UMU, Python, or Steam Runtime object.

Network containment during UMU execution is a core/runtime responsibility and
must be verified separately on the target host.

## Privacy

Preferences contain only user-selected paths and UI values. Local operation
receipts are sanitized summaries and remain outside the Vault. Raw command
logs are not persisted automatically.

Play and Remove arguments are parsed with `shlex` and passed as process arguments without a shell. Verify accepts no extra arguments.

## Local receipts

Local receipts keep only stable component identity facts from the core result. They do not persist raw backend result objects, command output, or argument values. Absolute target paths remain local private state and must be sanitized before publication.
