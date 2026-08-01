from __future__ import annotations

from dataclasses import dataclass
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Iterable


class CoreResolutionError(RuntimeError):
    pass


_REQUIRED_EXPERIMENTAL_COMMANDS = (
    "discover-bottles-path",
    "list-preserved-runners",
    "list-shared-umu-runtimes",
    "materialize-experimental",
    "verify-playable",
    "run-playable",
    "remove-playable",
    "verify-umu",
    "run-umu",
    "remove-umu",
    "verify-bottles-deployment",
    "run-bottles",
    "remove-bottles-deployment",
)


@dataclass(frozen=True, slots=True)
class CoreInfo:
    command: tuple[str, ...]
    version: str
    origin: str
    commands: tuple[str, ...]


def _regular_executable(path: Path) -> Path:
    try:
        resolved = path.expanduser().resolve(strict=True)
        metadata = resolved.lstat()
    except OSError as exc:
        raise CoreResolutionError(
            f"Core executable cannot be resolved: {path}"
        ) from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or not os.access(resolved, os.X_OK)
    ):
        raise CoreResolutionError(
            f"Core executable is not a regular executable: {resolved}"
        )
    return resolved


def _valid_source(candidate: Path) -> Path | None:
    try:
        root = candidate.expanduser().resolve(strict=True)
    except OSError:
        return None
    if (
        root.is_dir()
        and not root.is_symlink()
        and (root / "pyproject.toml").is_file()
        and (
            root
            / "src"
            / "offline_game_vault"
            / "cli.py"
        ).is_file()
    ):
        return root
    return None


def _automatic_source_candidates() -> tuple[Path, ...]:
    package_root = Path(__file__).resolve().parents[3]
    return (
        package_root.parent / "offline-game-vault",
        Path.cwd().parent / "offline-game-vault",
        Path.cwd() / "offline-game-vault",
    )


def resolve_core_source() -> Path | None:
    configured = os.environ.get("OGV_SOURCE_ROOT")
    if configured:
        source = _valid_source(Path(configured))
        if source is None:
            raise CoreResolutionError(
                "OGV_SOURCE_ROOT does not point to a compatible "
                "offline-game-vault checkout"
            )
        return source

    for candidate in _automatic_source_candidates():
        source = _valid_source(candidate)
        if source is not None:
            return source
    return None


def _source_command(
    source: Path,
    environment: dict[str, str],
) -> tuple[list[str], dict[str, str]]:
    existing = environment.get("PYTHONPATH", "")
    prefix = str(source / "src")
    environment["PYTHONPATH"] = (
        prefix if not existing else prefix + os.pathsep + existing
    )
    return [
        sys.executable,
        "-B",
        "-m",
        "offline_game_vault.cli",
    ], environment


def resolve_ogv_command() -> tuple[list[str], dict[str, str]]:
    """Resolve one core implementation for every backend.

    Explicit configuration is authoritative. A compatible source checkout is
    preferred over an installed command so development runs cannot silently
    pick an older system-wide ``ogv``.
    """

    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONUNBUFFERED"] = "1"

    configured_executable = os.environ.get("OGV_EXECUTABLE")
    if configured_executable:
        executable = _regular_executable(Path(configured_executable))
        return [str(executable)], environment

    configured_source = os.environ.get("OGV_SOURCE_ROOT")
    if configured_source:
        source = resolve_core_source()
        assert source is not None
        return _source_command(source, environment)

    for candidate in _automatic_source_candidates():
        source = _valid_source(candidate)
        if source is not None:
            return _source_command(source, environment)

    installed = shutil.which("ogv")
    if installed:
        return [str(_regular_executable(Path(installed)))], environment

    raise CoreResolutionError(
        "offline-game-vault was not found. Install core 0.11.3 or newer, "
        "or set OGV_SOURCE_ROOT to its source checkout."
    )


def _run_probe(
    command: Iterable[str],
    environment: dict[str, str],
    argument: str,
) -> str:
    process = subprocess.run(
        [*command, argument],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if process.returncode != 0:
        detail = process.stderr.strip() or process.stdout.strip()
        raise CoreResolutionError(
            f"offline-game-vault probe failed: {detail[-2000:]}"
        )
    return process.stdout.strip()


def _numeric_version(value: str) -> tuple[int, int, int] | None:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", value)
    if match is None:
        return None
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def inspect_core(
    required_commands: Iterable[str] = _REQUIRED_EXPERIMENTAL_COMMANDS,
) -> CoreInfo:
    command, environment = resolve_ogv_command()
    version_text = _run_probe(command, environment, "--version")
    help_text = _run_probe(command, environment, "--help")

    match = re.search(r"\bogv\s+([0-9][A-Za-z0-9._+-]*)\b", version_text)
    version = match.group(1) if match else version_text
    numeric_version = _numeric_version(version)
    if numeric_version is None or numeric_version < (0, 11, 3):
        raise CoreResolutionError(
            "The resolved offline-game-vault core is too old. "
            f"Found {version!r}; core 0.11.3 or newer is required "
            "for canonical operational scripts and offline UMU validation."
        )

    missing = [
        item
        for item in required_commands
        if not re.search(rf"(?<![A-Za-z0-9-]){re.escape(item)}(?![A-Za-z0-9-])", help_text)
    ]
    if missing:
        raise CoreResolutionError(
            "The resolved offline-game-vault core is incompatible. "
            "Missing command(s): "
            + ", ".join(missing)
            + ". Install core 0.11.3 or newer, or point OGV_SOURCE_ROOT "
            "to the updated checkout."
        )

    configured_executable = os.environ.get("OGV_EXECUTABLE")
    configured_source = os.environ.get("OGV_SOURCE_ROOT")
    if configured_executable:
        origin = f"executable:{command[0]}"
    elif configured_source:
        origin = f"source:{Path(configured_source).expanduser()}"
    elif len(command) > 1:
        source = resolve_core_source()
        origin = f"source:{source}" if source is not None else "source"
    else:
        origin = f"PATH:{command[0]}"

    return CoreInfo(
        command=tuple(command),
        version=version,
        origin=origin,
        commands=tuple(required_commands),
    )


def resolve_ogv_executable() -> Path:
    """Return a real executable for legacy helpers that require one path."""

    command, environment = resolve_ogv_command()
    if len(command) == 1:
        return Path(command[0])

    cache_base = Path(
        os.environ.get(
            "XDG_CACHE_HOME",
            str(Path.home() / ".cache"),
        )
    )
    wrapper_dir = cache_base / "offline-game-vault-gui"
    wrapper_dir.mkdir(parents=True, exist_ok=True)
    wrapper = wrapper_dir / "ogv-core-wrapper"
    payload = (
        "#!/bin/sh\n"
        "set -eu\n"
        "export PYTHONDONTWRITEBYTECODE=1\n"
        "export PYTHONUNBUFFERED=1\n"
        f"export PYTHONPATH={environment['PYTHONPATH']!r}\n"
        f"exec {command[0]!r} -B -m offline_game_vault.cli \"$@\"\n"
    )
    if not wrapper.exists() or wrapper.read_text(encoding="utf-8") != payload:
        temporary = wrapper.with_name(wrapper.name + ".tmp")
        temporary.write_text(payload, encoding="utf-8", newline="\n")
        temporary.chmod(0o700)
        os.replace(temporary, wrapper)
    return _regular_executable(wrapper)
