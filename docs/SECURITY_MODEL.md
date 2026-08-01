# Security model

## Immutable input

The GUI treats the Vault as read-only input. The core verifies canonical
objects and materializes outside the Vault or into the explicitly selected
managed Bottles directory.

## No component acquisition

The GUI performs no network lookup or download. It only lists runners verified by core 0.11.3 from the current Vault. Shared UMU runtimes are resolved internally from objects marked shared. No system Wine,
system Proton, or arbitrary installed Bottles runner is used as fallback.

## Safe paths

The GUI rejects:

- a destination parent inside the Vault;
- symlinked destination or Bottles directories;
- an existing unrecognized target for materialization;
- missing capsule files;
- backend-incompatible runner selections.

The core remains responsible for archive traversal, special files, symlink
escape, object hashes, and publication semantics.

## Acceptance is not access control

`verified`, `candidate`, `not_tested`, `experimental`, and `unavailable` are
evidence states. They are not security permissions. Blocking a test because it
has not already been tested creates a circular workflow and is intentionally
avoided.

## Removal

Removal is destructive to mutable derivatives. The GUI requires explicit
confirmation that state was preserved and, for Bottles, that related processes
were stopped. The immutable Vault is never removed.

## Logs and privacy

Operation logs can contain host paths. Do not archive raw GUI, Wine, Proton,
UMU, Bottles, DXVK, or VKD3D logs in a public package. Run the repository
privacy audit before release.
