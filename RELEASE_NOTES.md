# Release notes

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
