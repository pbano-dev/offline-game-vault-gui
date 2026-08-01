# Acceptance boundary

## Structural result

A successful GUI materialization establishes only that:

- the selected capsule was readable;
- preserved objects and runner matched the Vault records;
- path and archive checks passed;
- the requested backend derivative was assembled;
- its backend receipt was written.

It does not establish that the game is functionally accepted.

## Experimental state

Every user-requested combination is recorded as experimental and starts with:

```text
acceptance_inherited: false
```

This remains true even when the source profile or runner participated in a
different verified combination.

## Functional acceptance

Acceptance belongs to the exact combination of:

```text
capsule
source profile/layout
backend
runner or Proton
shared UMU runtime identity where applicable
state selection
host
```

A real acceptance run should cover, as applicable:

- canonical launch;
- Steam not running;
- exterior network blocked;
- existing save loaded;
- DLC recognized and real DLC content loaded;
- video and audio;
- controller and hotplug;
- normal shutdown;
- relocation;
- clean restoration.

The GUI allows testing before acceptance because testing is how acceptance
evidence is created.
