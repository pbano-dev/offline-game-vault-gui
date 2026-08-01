from __future__ import annotations

from pathlib import Path


class NeutralProfileError(RuntimeError):
    pass


def validate_neutral_bottles_source(path: Path) -> Path:
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_dir():
        raise NeutralProfileError(
            "Neutral Bottles source is not a regular directory"
        )
    return candidate.resolve(strict=True)


def materialize_neutral_bottle_source(
    source: Path,
    destination: Path,
) -> Path:
    import shutil

    source = validate_neutral_bottles_source(source)
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise NeutralProfileError("Destination already exists")
    shutil.copytree(source, destination, symlinks=True)
    return destination
