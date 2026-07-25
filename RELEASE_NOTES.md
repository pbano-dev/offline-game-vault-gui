# Release notes

## 0.2.6

### Direct-Wine real-path correction

- Launches imported neutral games from the real materialized game directory
  instead of from the compatibility symlink inside the prefix.
- Uses the real game directory as the declared working directory when the
  neutral contract requests the game installation directory.
- Remaps protected game files to the real game source while retaining the
  prefix link for Windows-path compatibility.
- Adds regression coverage that rejects a symlinked working directory and
  verifies the real entrypoint, working directory, and protected executable.
- Direct-Wine remains `not_tested` until a complete real launch, save load,
  normal shutdown, and clean removal are accepted.

## 0.2.5

### Direct-Wine protected-path correction

- Remapped neutral `prefix/...` protected-file declarations to the actual
  derived prefix location under `source/payload/prefix-template`.
- Added a filesystem-level regression test that verifies the protected
  executable through the generated relative game-directory link.
- Kept the neutral game object materialized only once and preserved the
  no-duplicate-dependency layout introduced in 0.2.3.
- Direct-Wine remains `not_tested` until a complete launch, save load, normal
  shutdown, and clean removal are accepted on a real materialization.

## 0.2.4

### Public repository preparation

- Prepared a standalone, Git-ready source tree.
- Standardized application labels, diagnostics, generated launchers, scripts,
  test fixtures, and documentation in English.
- Consolidated all release information in this single file.
- Added a repository privacy audit.
- Added a reproducible source-packaging helper.
- Added continuous integration and development documentation.
- Removed caches, compiled Python files, local logs, and generated work trees.

### Functional changes carried forward

- Supports imported neutral game objects.
- Supports candidate profiles for Bottles, Direct-Wine, and Windows export.
- Supports runner selection at materialization time.
- Supports atomic multi-item save sets.
- Converts neutral objects into derived Bottles sources while preserving the
  materialization receipt and runner object.
- Resolves Bottles sources under `objects/<object-id>`.
- Generates Direct-Wine layouts in which each dependency appears only once.
- Places the game inside a neutral Direct-Wine prefix through a relative link.
- Performs preflight validation of derived Bottles sources.
- Preserves compatibility with legacy single-item save sets and existing
  capsules.

### Validation status

- The packaged source tree passes 76 automated tests.
- Python sources pass AST parsing.
- Shell scripts pass `bash -n`.
- The repository privacy audit passes.
- Bottles materialization has been functionally tested with
  ELDEN RING NIGHTREIGN:
  - without a save set;
  - with a multi-item save set.
- Direct-Wine remains a candidate workflow pending functional acceptance after
  the dependency-layout correction.
- Native Windows export remains untested.

## 0.2.3

- Corrected Direct-Wine layout generation so a dependency cannot be emitted
  twice in `playable.layout`.
- Materialized neutral Direct-Wine sources once and exposed the game in the
  prefix through a relative link.

## 0.2.2

- Corrected Bottles neutral-object resolution.
- Preserved the wrapper receipt, runner object, and object-scoped source during
  Bottles conversion.
- Added a derived-source preflight check.

## 0.2.1

- Corrected imported-candidate runner reuse and workspace preparation behavior.
