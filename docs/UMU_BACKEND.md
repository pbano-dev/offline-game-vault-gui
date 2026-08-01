# UMU backend

UMU materialization is user-selectable for every game when the Vault contains:

1. a Proton runner whose core catalog reports `umu` compatibility;
2. a reusable shared object containing the preserved UMU launcher, portable
   Python, and Steam Linux Runtime layout.

The GUI lists only the preserved Proton runners:

```text
ogv list-preserved-runners --json
```

It then calls:

```text
ogv materialize-experimental \
  --backend umu \
  --runner <PRESERVED_RUNNER_ID>
```

The core resolves the shared UMU runtime automatically. The user never selects
DMC5, DSR, or any other game's profile as a backend template. A qualifying
runtime object must be marked `shared: true`, carry the `runtime` role, and
remain inside the Vault.

No game, including DMC5, is restricted to UMU. Conversely, the presence of an
accepted UMU profile does not prevent testing Bottles or Direct-Wine.

A new combination is always experimental:

```text
kind: experimental
acceptance_inherited: false
```

The core may synthesize its source layout from an existing compatible Linux
profile. The source capsule and accepted profiles remain unchanged.

The GUI does not download Steam Linux Runtime, Proton, Python, UMU, Foz, or any
other missing component.

## Offline execution invariant

Before publishing an UMU materialization, core 0.11.3 verifies one complete
preserved `steamrtN` tree, including `VERSIONS.txt`, executable
`_v2-entry-point`, `pressure-vessel`, and exactly one
`steamrtN_platform_*` directory.

The generated `JUGAR.sh` launches through a private network namespace and sets
`UMU_RUNTIME_UPDATE=0`. If any runtime piece is absent, materialization or
verification aborts; UMU is never allowed to repair the derivative by
downloading a runtime.
