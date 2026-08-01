from __future__ import annotations

import json
import re
import stat
import tarfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from .model import RunnerRecord


class RunnerCatalogError(RuntimeError):
    pass


_RUNNER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise RunnerCatalogError(f"{label} must be a regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RunnerCatalogError(
            f"{label} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise RunnerCatalogError(
            f"{label} does not contain a JSON object"
        )
    return value


def _safe_relative(value: Any, label: str) -> PurePosixPath:
    if (
        not isinstance(value, str)
        or not value
        or "\x00" in value
        or "\\" in value
    ):
        raise RunnerCatalogError(
            f"{label} is not a safe relative path"
        )
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise RunnerCatalogError(
            f"{label} is not a safe relative path"
        )
    return path


def _strip_archive_suffix(label: str) -> str:
    lowered = label.casefold()
    for suffix in (".tar.gz", ".tgz", ".tar.zst", ".tar", ".zip"):
        if lowered.endswith(suffix):
            return label[: -len(suffix)]
    return label


def _archive_format(path: Path, label: str) -> str:
    with path.open("rb", buffering=0) as handle:
        magic = handle.read(4)
    if magic.startswith(b"\x1f\x8b\x08"):
        return "tar.gz"
    if magic == b"\x28\xb5\x2f\xfd":
        return "tar.zst"
    if magic.startswith(b"PK\x03\x04"):
        return "zip"
    if label.casefold().endswith(".tar"):
        return "tar"
    raise RunnerCatalogError(
        f"Could not determine the format of {path.name}"
    )


def _tar_members(path: Path, archive_format: str) -> set[str]:
    if archive_format == "tar.zst":
        try:
            import zstandard  # type: ignore
        except ModuleNotFoundError:
            # tarfile in supported Python builds may know zstd itself.
            try:
                with tarfile.open(path, mode="r:*") as archive:
                    return {
                        member.name.rstrip("/")
                        for member in archive
                        if member.name.rstrip("/")
                    }
            except tarfile.TarError as exc:
                raise RunnerCatalogError(
                    "Cannot inspect tar.zst runner; install python-zstandard"
                ) from exc

        members: set[str] = set()
        try:
            with path.open("rb") as raw:
                with zstandard.ZstdDecompressor().stream_reader(raw) as reader:
                    with tarfile.open(fileobj=reader, mode="r|") as archive:
                        for member in archive:
                            name = member.name.rstrip("/")
                            if name:
                                members.add(name)
        except (OSError, tarfile.TarError) as exc:
            raise RunnerCatalogError(
                f"Could not inspect {path.name}: {exc}"
            ) from exc
        return members

    try:
        with tarfile.open(path, mode="r:*") as archive:
            return {
                member.name.rstrip("/")
                for member in archive
                if member.name.rstrip("/")
            }
    except (OSError, tarfile.TarError) as exc:
        raise RunnerCatalogError(
            f"Could not inspect {path.name}: {exc}"
        ) from exc


def _members(path: Path, archive_format: str) -> set[str]:
    if archive_format == "zip":
        try:
            with zipfile.ZipFile(path) as archive:
                return {
                    name.rstrip("/")
                    for name in archive.namelist()
                    if name.rstrip("/")
                }
        except (OSError, zipfile.BadZipFile) as exc:
            raise RunnerCatalogError(
                f"Could not inspect {path.name}: {exc}"
            ) from exc
    return _tar_members(path, archive_format)


def _archive_hint(
    path: Path,
    label: str,
) -> tuple[str, str, str, str | None, str]:
    archive_format = _archive_format(path, label)
    members = _members(path, archive_format)
    roots = {
        PurePosixPath(name).parts[0]
        for name in members
        if PurePosixPath(name).parts
    }
    if len(roots) != 1:
        raise RunnerCatalogError(
            f"Runner archive {label} does not have exactly one root"
        )
    root = next(iter(roots))

    proton = f"{root}/proton"
    wine_candidates = (
        (f"{root}/files/bin/wine", f"{root}/files/bin/wineserver"),
        (f"{root}/bin/wine", f"{root}/bin/wineserver"),
    )
    wine_pair = next(
        (
            (wine, wineserver)
            for wine, wineserver in wine_candidates
            if wine in members and wineserver in members
        ),
        None,
    )

    if proton in members:
        wine_path = (
            wine_pair[0][len(root) + 1 :]
            if wine_pair is not None
            else "files/bin/wine"
        )
        wineserver_path = (
            wine_pair[1][len(root) + 1 :]
            if wine_pair is not None
            else "files/bin/wineserver"
        )
        return (
            root,
            wine_path,
            wineserver_path,
            "proton",
            archive_format,
        )

    if wine_pair is None:
        raise RunnerCatalogError(
            f"Runner archive {label} contains neither Proton nor Wine"
        )
    return (
        root,
        wine_pair[0][len(root) + 1 :],
        wine_pair[1][len(root) + 1 :],
        None,
        archive_format,
    )


def _registrations(
    collection_root: Path,
) -> dict[str, dict[str, Any]]:
    path = collection_root / "COLLECTION_LAYOUT.json"
    if not path.is_file() or path.is_symlink():
        return {}
    try:
        document = _load_json(path, "COLLECTION_LAYOUT.json")
    except RunnerCatalogError:
        return {}
    result: dict[str, dict[str, Any]] = {}
    raw = document.get("registrations")
    if not isinstance(raw, list):
        return result
    for item in raw:
        if not isinstance(item, dict):
            continue
        digest = item.get("object_sha256")
        if (
            isinstance(digest, str)
            and digest.startswith("sha256:")
            and _SHA256_RE.fullmatch(digest[7:])
        ):
            result[digest[7:]] = item
    return result


def _inventory_map(
    collection_root: Path,
) -> dict[str, int]:
    path = (
        collection_root
        / "01_IMMUTABLE_VAULT"
        / "VAULT_INVENTORY.json"
    )
    document = _load_json(path, "VAULT_INVENTORY.json")
    raw = document.get("objects")
    if not isinstance(raw, list):
        raise RunnerCatalogError(
            "VAULT_INVENTORY.json objects is not an array"
        )
    result: dict[str, int] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        digest = item.get("digest")
        size = item.get("bytes")
        if (
            isinstance(digest, str)
            and digest.startswith("sha256:")
            and _SHA256_RE.fullmatch(digest[7:])
            and isinstance(size, int)
            and size >= 0
        ):
            result[digest[7:]] = size
    return result


def scan_runners(
    collection_root: Path,
) -> tuple[tuple[RunnerRecord, ...], tuple[str, ...]]:
    root = Path(collection_root).expanduser()
    if root.is_symlink() or not root.is_dir():
        raise RunnerCatalogError(
            "Collection root is not a regular directory"
        )
    root = root.resolve(strict=True)
    index = _load_json(root / "INDEX.json", "INDEX.json")
    objects = index.get("objects")
    if not isinstance(objects, list):
        raise RunnerCatalogError("INDEX.json objects is not an array")

    inventory = _inventory_map(root)
    registrations = _registrations(root)
    immutable = root / "01_IMMUTABLE_VAULT"

    records: list[RunnerRecord] = []
    warnings: list[str] = []
    for item in objects:
        if not isinstance(item, dict) or item.get("role") != "shared-runner":
            continue

        digest = item.get("sha256")
        label = item.get("label")
        relative_raw = item.get("path")
        size = item.get("size")
        if (
            not isinstance(digest, str)
            or _SHA256_RE.fullmatch(digest) is None
            or not isinstance(label, str)
            or not label
            or not isinstance(size, int)
            or size < 0
        ):
            warnings.append("Skipped malformed shared-runner INDEX entry")
            continue

        try:
            relative = _safe_relative(
                relative_raw,
                f"{label}.path",
            )
        except RunnerCatalogError as exc:
            warnings.append(str(exc))
            continue

        object_path = immutable.joinpath(*relative.parts)
        try:
            resolved = object_path.resolve(strict=True)
            resolved.relative_to(immutable.resolve(strict=True))
            metadata = object_path.lstat()
        except (OSError, ValueError) as exc:
            warnings.append(f"{label}: object unavailable: {exc}")
            continue

        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or metadata.st_size != size
            or inventory.get(digest) != size
        ):
            warnings.append(
                f"{label}: object size/type does not match the inventory"
            )
            continue

        try:
            (
                source_root,
                wine_path,
                wineserver_path,
                proton_path,
                archive_format,
            ) = _archive_hint(object_path, label)
        except RunnerCatalogError as exc:
            warnings.append(str(exc))
            continue

        registration = registrations.get(digest, {})
        registered_id = registration.get("runner_id")
        candidate_id = (
            registered_id
            if isinstance(registered_id, str)
            and _RUNNER_ID_RE.fullmatch(registered_id)
            else _strip_archive_suffix(label)
        )
        if _RUNNER_ID_RE.fullmatch(candidate_id) is None:
            warnings.append(f"{label}: could not derive a portable runner ID")
            continue

        acceptance = registration.get("acceptance_status")
        if not isinstance(acceptance, str) or not acceptance:
            acceptance = "not_tested"

        kind = "proton" if proton_path is not None else "wine"
        compatible = (
            ("umu",)
            if kind == "proton"
            else ("direct-wine", "bottles")
        )
        records.append(
            RunnerRecord(
                runner_id=candidate_id,
                digest=digest,
                archive_path=relative.as_posix(),
                size=size,
                format=archive_format,
                source_root=source_root,
                wine_path=wine_path,
                wineserver_path=wineserver_path,
                proton_path=proton_path,
                kind=kind,
                compatible_backends=compatible,
                metadata_source=(
                    "COLLECTION_LAYOUT.json"
                    if registration
                    else "INDEX.json+archive"
                ),
                acceptance_status=acceptance,
            )
        )

    records.sort(
        key=lambda item: (
            0 if item.kind == "proton" else 1,
            item.runner_id.casefold(),
        )
    )
    return tuple(records), tuple(warnings)
