# Release notes

## 0.3.3

### Managed Bottles deployment

- Requires core 0.11.3.
- The GUI discovers the active managed Bottles directory through the core and
  shows it as read-only information; it cannot be replaced with an arbitrary
  output directory.
- Bottles materialization is requested by bottle name only. The core stages
  and publishes inside the directory reported by `bottles-cli`.

### Exact offline UMU runtime resolution

- UMU exposes no backend-template selector.
- The selected preserved Proton runner determines the required Steam Linux
  Runtime through its archived `toolmanifest.vdf`.
- Incomplete runtimes and runtimes from a different family are excluded before
  materialization. A missing exact match is reported before a game tree is
  copied.
- The generated `JUGAR.sh`, `VERIFICAR.sh`, and `DESINSTALAR.sh` remain the
  only operational entry points used by the GUI.

## 0.3.2

### Canonical materialization operations

- Requires core 0.11.2.
- Bottles, Direct-Wine, and UMU materializations are recognized only when they
  contain executable `JUGAR.sh`, `VERIFICAR.sh`, and `DESINSTALAR.sh`.
- **Materialize & Play** first materializes and then invokes the generated
  `JUGAR.sh`; the GUI no longer reconstructs backend launch commands.
- Verify, Play, and Remove call the corresponding generated script for every
  backend.

### Offline UMU enforcement

- UMU materialization must contain a complete preserved `steamrtN` runtime.
- Missing runtime components abort before launch.
- Network isolation and `UMU_RUNTIME_UPDATE=0` are enforced by the generated
  UMU operational runtime, preventing repair downloads.

## 0.3.1

### Destination-local Bottles staging

- Requires core 0.11.1.
- Bottles prematerialization now occurs inside the selected managed Bottles
  directory instead of `/tmp`.
- Hidden staging is cleaned after success or failure and final publication
  remains atomic on the selected filesystem.

### Automatic UMU runtime resolution

- Removed the **Preserved UMU backend** selector.
- The GUI no longer exposes another game's capsule/profile as a backend choice.
- UMU requests contain only the selected game, source layout, and preserved
  Proton runner; core resolves a reusable shared runtime automatically.
- No `--umu-backend` argument is emitted.

## 0.3.0

### Experimental variants are user-selectable

- Every discovered game exposes Bottles, Direct-Wine, and UMU/Proton.
- Removed title-specific and acceptance-status backend restrictions.
- Profiles with `candidate`, `not_tested`, `experimental`, or `unavailable`
  status remain selectable as source layouts.
- When no exact backend profile exists, core 0.11.0 synthesizes one without
  rewriting the capsule.

### Preserved runners only

- Runner discovery is delegated to `ogv list-preserved-runners`.
- Only hash-verified Vault objects are shown.
- Proton runners may be offered to Bottles and Direct-Wine when the core
  reports the Wine/Wineserver pair as structurally usable.
- No download, host-runner fallback, or silent Bottles-runner reuse exists.

### Materialize and play

- Added a single **Materialize & Play** operation backed by
  `ogv materialize-experimental --play`.
- Existing experimental derivatives can be verified, played, and removed with
  their backend-specific core commands.
- Added selection of preserved UMU backend templates.
- Windows export is intentionally omitted from this phase.

### Core resolution

- Requires core 0.11.0 or newer.
- Validates command capabilities before enabling materialization.
- Prefers an explicit or sibling source checkout over an older `ogv` in
  `PATH`.
- Adds a GUI checkout selector for the current session.

### Validation

- Unit tests cover unrestricted backend selection, structural runner
  filtering, command construction, UMU templates, and old-core rejection.
- Synthetic end-to-end tests exercise materialization and verification for
  Bottles, Direct-Wine, and UMU against core 0.11.0.
