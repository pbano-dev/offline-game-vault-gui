from __future__ import annotations

import os
import shutil
from pathlib import Path

from .model import ValidatedRequest


class SandboxError(RuntimeError):
    pass


def _resolve_executable(
    env_name: str,
    default: str | None = None,
    command_name: str | None = None,
) -> Path:
    configured = os.environ.get(env_name)
    candidate = configured or default
    if not candidate and command_name:
        candidate = shutil.which(command_name)
    if not candidate:
        raise SandboxError(
            f"Required executable was not found ({env_name})"
        )

    path = Path(candidate).expanduser()
    if path.is_symlink():
        path = path.resolve(strict=True)
    if not path.is_file() or not os.access(path, os.X_OK):
        raise SandboxError(f"Invalid executable: {path}")
    return path.resolve(strict=True)


def resolve_bwrap() -> Path:
    return _resolve_executable("OGV_BWRAP", default="/usr/bin/bwrap")


def resolve_ogv() -> Path:
    return _resolve_executable("OGV_EXECUTABLE", command_name="ogv")


def resolve_state_bridge() -> Path:
    project_root = Path(__file__).resolve().parents[2]
    default = project_root / "scripts/ogv-state-capsule-bridge.py"
    return _resolve_executable(
        "OGV_STATE_BRIDGE",
        default=str(default),
    )


def build_command(
    request: ValidatedRequest,
    *,
    bwrap: Path,
    ogv: Path,
    capsule_path: Path | None = None,
    state_bridge: Path | None = None,
) -> list[str]:
    effective_capsule = (
        Path(capsule_path)
        if capsule_path is not None
        else request.capsule_path
    )
    use_state_bridge = (
        request.mode == "playable"
        and request.overlay_required
        and request.state_backup is not None
    )
    if use_state_bridge and state_bridge is None:
        raise SandboxError(
            "A state-bearing overlay requires the original-capsule bridge"
        )

    subcommand = (
        "materialize-playable"
        if request.mode == "playable"
        else "materialize"
    )
    worker = Path(state_bridge) if use_state_bridge else Path(ogv)

    command = [
        str(Path(bwrap)),
        "--ro-bind",
        "/",
        "/",
        "--bind",
        str(request.destination_parent),
        str(request.destination_parent),
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--unshare-net",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--die-with-parent",
        "--new-session",
        "--chdir",
        str(request.destination_parent),
        str(worker),
        subcommand,
        "--capsule",
        str(effective_capsule),
    ]
    if use_state_bridge:
        command.extend(
            [
                "--state-capsule",
                str(request.capsule_path),
            ]
        )
    command.extend(
        [
            "--profile",
            request.profile_id,
            "--vault-root",
            str(request.immutable_vault_root),
            "--destination",
            str(request.destination),
        ]
    )
    if request.mode == "playable" and request.state_backup is not None:
        command.extend(["--state-backup", str(request.state_backup)])
    command.append("--json")
    return command



def build_verify_state_backup_command(
    capsule: Path,
    backup: Path,
    *,
    ogv: Path,
) -> list[str]:
    return [
        str(Path(ogv)),
        "verify-state-backup",
        "--capsule",
        str(Path(capsule)),
        "--backup",
        str(Path(backup)),
        "--json",
    ]


def build_restore_state_command(
    request: ValidatedRequest,
    *,
    state_root: Path,
    backup: Path,
    snapshot: Path,
    bwrap: Path,
    ogv: Path,
) -> list[str]:
    if request.backend_id != "bottles":
        raise SandboxError(
            "GUI restore-state is used only for Bottles"
        )

    destination_parent = request.destination_parent.resolve(
        strict=True
    )
    effective_state_root = Path(state_root).resolve(strict=False)

    writable_roots = [destination_parent]
    try:
        effective_state_root.relative_to(destination_parent)
    except ValueError:
        if request.bottles_path is None:
            raise SandboxError(
                "The state root is outside the destination and there is no "
                "validated Bottles path"
            )
        bottles_path = request.bottles_path.resolve(strict=True)
        try:
            effective_state_root.relative_to(bottles_path)
        except ValueError as exc:
            raise SandboxError(
                "The state root is outside the allowed write roots "
                "allowed"
            ) from exc
        writable_roots.append(bottles_path)

    command = [
        str(Path(bwrap)),
        "--ro-bind",
        "/",
        "/",
    ]
    for writable_root in writable_roots:
        command.extend(
            [
                "--bind",
                str(writable_root),
                str(writable_root),
            ]
        )
    command.extend(
        [
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
            "--unshare-net",
            "--unshare-pid",
            "--unshare-ipc",
            "--unshare-uts",
            "--die-with-parent",
            "--new-session",
            "--chdir",
            str(request.destination_parent),
            str(Path(ogv)),
            "restore-state",
            "--capsule",
            str(request.capsule_path),
            "--state-root",
            str(effective_state_root),
            "--backup",
            str(Path(backup)),
            "--snapshot",
            str(Path(snapshot)),
            "--confirm-stopped",
            "--json",
        ]
    )
    return command

def build_verify_playable_command(
    destination: Path,
    *,
    ogv: Path,
) -> list[str]:
    return [
        str(Path(ogv)),
        "verify-playable",
        "--destination",
        str(Path(destination)),
        "--json",
    ]


def build_run_playable_command(
    destination: Path,
    *,
    ogv: Path,
) -> list[str]:
    return [
        str(Path(ogv)),
        "run-playable",
        "--destination",
        str(Path(destination)),
        "--json",
    ]


def build_deploy_bottles_command(
    request: ValidatedRequest,
    *,
    bwrap: Path,
    ogv: Path,
) -> list[str]:
    if (
        request.backend_id != "bottles"
        or request.bottles_path is None
        or request.bottle_name is None
    ):
        raise SandboxError("The request does not contain a Bottles deployment")
    return [
        str(Path(bwrap)),
        "--ro-bind",
        "/",
        "/",
        "--bind",
        str(request.bottles_path),
        str(request.bottles_path),
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--unshare-net",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--die-with-parent",
        "--new-session",
        "--chdir",
        str(request.destination_parent),
        str(Path(ogv)),
        "deploy-bottles",
        "--capsule",
        str(request.capsule_path),
        "--profile",
        request.profile_id,
        "--materialization",
        str(request.destination),
        "--bottles-path",
        str(request.bottles_path),
        "--name",
        request.bottle_name,
        "--json",
    ]


def build_verify_bottles_command(
    bottles_path: Path,
    bottle_name: str,
    *,
    ogv: Path,
) -> list[str]:
    return [
        str(Path(ogv)),
        "verify-bottles-deployment",
        "--bottles-path",
        str(Path(bottles_path)),
        "--name",
        bottle_name,
        "--json",
    ]


def build_run_bottles_command(
    bottles_path: Path,
    bottle_name: str,
    *,
    ogv: Path,
) -> list[str]:
    return [
        str(Path(ogv)),
        "run-bottles",
        "--bottles-path",
        str(Path(bottles_path)),
        "--name",
        bottle_name,
        "--json",
    ]


def build_remove_materialization_command(
    request: ValidatedRequest,
    *,
    bwrap: Path,
    ogv: Path,
) -> list[str]:
    if request.backend_id != "bottles":
        raise SandboxError(
            "Only the Bottles workflow removes a transient base source"
        )
    return [
        str(Path(bwrap)),
        "--ro-bind",
        "/",
        "/",
        "--bind",
        str(request.destination_parent),
        str(request.destination_parent),
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--unshare-net",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--die-with-parent",
        "--new-session",
        "--chdir",
        str(request.destination_parent),
        str(Path(ogv)),
        "remove-materialization",
        "--destination",
        str(request.destination),
        "--confirm-state-preserved",
        "--json",
    ]
