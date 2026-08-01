from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Sequence

from .core import resolve_ogv_command


class SandboxError(RuntimeError):
    pass


def resolve_bwrap() -> Path:
    value = os.environ.get("OGV_BWRAP") or shutil.which("bwrap")
    if not value:
        raise SandboxError("bwrap was not found")
    path = Path(value).expanduser().resolve(strict=True)
    if not path.is_file() or not os.access(path, os.X_OK):
        raise SandboxError("bwrap is not executable")
    return path


def resolve_ogv() -> list[str]:
    command, _environment = resolve_ogv_command()
    return command


def build_command(
    arguments: Sequence[str],
    *,
    destination_parent: Path,
    isolate_network: bool = True,
) -> list[str]:
    bwrap = resolve_bwrap()
    command = [
        str(bwrap),
        "--ro-bind", "/", "/",
        "--bind", str(destination_parent), str(destination_parent),
        "--proc", "/proc",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
        "--die-with-parent",
        "--new-session",
    ]
    if isolate_network:
        command.append("--unshare-net")
    core, _environment = resolve_ogv_command()
    return [*command, *core, *arguments]
