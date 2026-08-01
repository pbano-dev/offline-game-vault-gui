from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class SharedBackendError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SharedBackendRecord:
    backend_id: str
    digest: str
    size: int
    archive_path: str
    object_path: Path
    status: str = "not_tested"


def validate_shared_backend_record(
    collection_root: Path,
    record: SharedBackendRecord,
) -> None:
    immutable = Path(collection_root) / "01_IMMUTABLE_VAULT"
    path = immutable / record.archive_path
    if path.is_symlink() or not path.is_file():
        raise SharedBackendError("Shared backend object is unavailable")
    if path.stat().st_size != record.size:
        raise SharedBackendError("Shared backend object size changed")
