# Complete source-tree deployment

This archive is a complete repository source tree, not an updater, patcher,
fixer, or builder.

Recommended Git procedure:

```bash
git switch -c feature/state-backup-timeline-0.5.0a4
```

Replace the tracked worktree with the extracted contents while preserving only
the repository's `.git` directory. Review the full diff before committing.

Do not copy the source tree over a dirty checkout. Do not place private Vault
data, logs, screenshots, credentials, or host-specific paths in the repository.

Validation:

```bash
./scripts/test.sh
./scripts/check-core-contract.sh ../offline-game-vault
./scripts/audit-privacy.sh
python3 -B tools/validate_repository.py
```

The source archive does not contain PySide6 wheels. A future offline deployment
must preserve exact compatible wheels and their hashes separately.
