from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class BottlesEnvironmentError(RuntimeError):
    pass


class BottlesOverrideError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class BottlesEnvironment:
    bottles_path: Path
    flatpak_app: str = "com.usebottles.bottles"


def scan_bottles_environment() -> BottlesEnvironment:
    from .experimental_service import discover_bottles_path

    try:
        path = discover_bottles_path()
    except Exception as exc:
        raise BottlesEnvironmentError(
            f"Cannot discover Bottles managed directory: {exc}"
        ) from exc
    return BottlesEnvironment(path)


def find_materialized_bottle_yml(root: Path) -> Path:
    matches = [
        path
        for path in Path(root).rglob("bottle.yml")
        if path.is_file() and not path.is_symlink()
    ]
    if len(matches) != 1:
        raise BottlesEnvironmentError(
            "Materialization does not contain exactly one bottle.yml"
        )
    return matches[0]


class temporary_runner_override:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    def __enter__(self) -> None:
        return None

    def __exit__(self, *_args: object) -> None:
        return None
