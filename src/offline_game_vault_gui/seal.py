from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib


@dataclass(frozen=True, slots=True)
class SealEntry:
    relative_path: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class CollectionSeal:
    entries: tuple[SealEntry, ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def capture_collection_seal(
    collection_root: Path,
    capsule_path: Path,
) -> CollectionSeal:
    collection_root = Path(collection_root).resolve(strict=True)
    candidates = [
        collection_root / "COLLECTION_LAYOUT.json",
        collection_root / "COLLECTION_SHA256.txt",
        collection_root / "INDEX.json",
        collection_root
        / "01_IMMUTABLE_VAULT"
        / "VAULT_INVENTORY.json",
        Path(capsule_path),
    ]

    entries: list[SealEntry] = []
    seen: set[Path] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        if path.is_symlink():
            raise RuntimeError(f"The critical seal does not allow a symbolic link: {path}")
        if not path.exists():
            continue
        if not path.is_file():
            raise RuntimeError(f"The critical seal expected a file: {path}")
        stat_result = path.stat()
        entries.append(
            SealEntry(
                relative_path=path.relative_to(collection_root).as_posix(),
                size=stat_result.st_size,
                sha256=_sha256(path),
            )
        )
    return CollectionSeal(tuple(entries))
