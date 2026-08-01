from __future__ import annotations

import hashlib
from pathlib import Path


class SealError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def capture_collection_seal(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for relative in (
        "INDEX.json",
        "COLLECTION_LAYOUT.json",
        "COLLECTION_SHA256.txt",
        "01_IMMUTABLE_VAULT/VAULT_INVENTORY.json",
    ):
        path = Path(root) / relative
        if path.is_symlink() or not path.is_file():
            raise SealError(f"Missing critical collection file: {relative}")
        result[relative] = _sha256(path)
    return result
