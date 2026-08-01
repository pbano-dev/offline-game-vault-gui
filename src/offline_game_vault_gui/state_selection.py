from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .model import SaveSetRecord


class StateSelectionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PreparedStateBackup:
    path: Path
    save_set_id: str | None


@contextmanager
def prepared_state_backup(
    save_set: SaveSetRecord | None,
    fallback: Path | None,
) -> Iterator[PreparedStateBackup | None]:
    if save_set is not None and save_set.source:
        value = save_set.source.get("state_backup")
        if isinstance(value, str) and value:
            path = Path(value)
            if path.is_dir() and not path.is_symlink():
                yield PreparedStateBackup(
                    path.resolve(strict=True),
                    save_set.save_set_id,
                )
                return
    if fallback is not None:
        yield PreparedStateBackup(fallback, None)
    else:
        yield None
