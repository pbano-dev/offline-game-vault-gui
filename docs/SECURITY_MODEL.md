# Security model

## Vault protection

The collection is exposed read-only to materialization workers. Writable access is limited to validated output locations and explicitly managed state locations.

## Path safety

The application rejects traversal, escaping symbolic links, unsafe archive members, unexpected special files, and destinations outside the selected local root.

## Network policy

Network isolation is separate from preservation. A backend may request an isolated execution mode, but the result must be functionally tested. Disabling runtime updates is not equivalent to network isolation.

## Runner handling

Runners are selected from preserved objects. The GUI does not download missing runners and does not silently fall back to another runner.

## Receipts and seals

Critical collection seals are checked before and after operations. Derived selections, temporary overlays, materializations, and removals produce receipts.

## Privacy

Raw runtime logs are not archival evidence by default. They may expose host paths, usernames, hostnames, UIDs, UUIDs, and session data. Store sanitized summaries instead.

## Acceptance

A successful extraction or launcher generation proves structural completion only. Gameplay, saves, DLC, video, audio, input, network policy, normal exit, relocation, and clean restoration require separate evidence.
