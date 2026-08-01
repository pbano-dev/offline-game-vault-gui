# Validation report for 0.3.3 source candidate

## Verified in the build environment

- 31 GUI unit tests pass.
- All Python files parse with `ast`.
- All shell scripts pass `bash -n`.
- Whitespace and privacy audits pass.
- Core capability probing requires Offline Game Vault 0.11.3 or newer.
- The active GUI contains no **Preserved UMU backend** selector and emits no
  `--umu-backend` argument.
- Bottles, Direct-Wine, and UMU remain selectable for every game.
- Only preserved runners returned by the core are shown.

## Operational-script integration covered by tests

- A materialization is recognized only when executable root-level
  `JUGAR.sh`, `VERIFICAR.sh`, and `DESINSTALAR.sh` are present with its
  backend receipt.
- **Materialize & Play** materializes first and then invokes `JUGAR.sh`.
- Play, Verify, and Remove invoke the generated backend-specific scripts
  instead of reconstructing core commands in the GUI.
- Direct-Wine, Bottles, and UMU all use the same script-dispatch path.

## Core integration expected from 0.11.3

- Bottles discovers its active managed directory through `bottles-cli`; the
  GUI cannot redirect deployment to an arbitrary folder.
- Bottles heavy staging and final publication occur inside that managed
  directory, not in `/tmp`.
- UMU reads the selected Proton runner's archived `toolmanifest.vdf`, resolves
  the exact required runtime family, and excludes incomplete or mismatched
  shared runtimes before copying a game.
- UMU gameplay runs with `PrivateNetwork=yes` and
  `UMU_RUNTIME_UPDATE=0`, so a missing runtime cannot be downloaded.

## Pending on the target host

- GTK4/libadwaita visual launch.
- Real Bottles materialization and gameplay of The Sims 2.
- Real UMU and Direct-Wine gameplay.
- Save/load, DLC, video, audio, controller, normal shutdown, relocation, and
  clean restoration.

No functional acceptance is claimed for a commercial game.
