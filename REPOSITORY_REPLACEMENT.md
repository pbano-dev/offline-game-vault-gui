# Repository replacement instructions

This ZIP represents the complete 0.4.1 source tree.

When applying it to a branch created from GUI 0.3.3:

1. preserve the branch's `.git` directory;
2. remove all other tracked files from the worktree;
3. copy the contents of this archive root into the repository root;
4. run `./scripts/test.sh`;
5. inspect `git status` and commit the replacement.

This replacement intentionally removes the previous modules whose names or
contracts encoded profile maturity, experimental variants, per-profile
ownership of reusable components, runner overrides, or a separate UMU
selection model.

The authoritative runtime path is now:

```text
catalog.py -> service.py -> core.py -> offline-game-vault 0.11.4
```

Post-materialization Play, Verify, and Remove operations invoke only the
generated root scripts published by the core.
