# State-free component migration

## Why the GUI changed

The previous GUI mixed recipe selection, historical evidence, reusable
component ownership, and post-materialization state. That made labels such as
`experimental`, `verified`, or `not_tested` appear to govern whether a user
could request a composition.

Core 0.11.4 separates those concerns:

- profiles are recipes;
- acceptance is independent evidence;
- runners are global preserved components;
- UMU/Python and Steam Linux Runtime are independent global components;
- the source capsule is not rewritten;
- only technical facts block composition.

The GUI 0.4.1 mirrors that contract directly. It no longer translates old
maturity labels, no longer manufactures per-game backend ownership, and no
longer searches for execution dependencies itself.

## Runtime state

The GUI never sanitizes Steam Runtime `var`. The core preserves archived
runtime state in the writable derivative and applies only narrow,
documented transformations. The original CAS object remains immutable.

## User-visible consequence

The user chooses a game, requested backend, optional source layout, and one
compatible preserved runner. UMU component-set information is diagnostic
because core 0.11.4 resolves the compatible backend/runtime set itself.
