from __future__ import annotations

import hashlib
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from offline_game_vault_gui.runners import scan_runners


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def make_archive(path: Path, root: str, proton: bool) -> tuple[str, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    members = [
        ("files/bin/wine", b"wine\n", 0o755),
        ("files/bin/wineserver", b"wineserver\n", 0o755),
    ]
    if proton:
        members.insert(0, ("proton", b"#!/bin/sh\n", 0o755))
    with tarfile.open(path, "w:gz") as archive:
        for name, payload, mode in members:
            info = tarfile.TarInfo(f"{root}/{name}")
            info.mode = mode
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest, path.stat().st_size


class RunnerTests(unittest.TestCase):
    def test_classifies_proton_and_wine_separately(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            collection = Path(temporary)
            immutable = collection / "01_IMMUTABLE_VAULT"
            proton_tmp = collection / "proton.tmp"
            wine_tmp = collection / "wine.tmp"
            proton_digest, proton_size = make_archive(
                proton_tmp, "Proton-Test", True
            )
            wine_digest, wine_size = make_archive(
                wine_tmp, "Wine-Test", False
            )

            objects = []
            inventory = []
            registrations = []
            for label, digest, size, source, runner_id in (
                (
                    "proton-test.tar.gz",
                    proton_digest,
                    proton_size,
                    proton_tmp,
                    "proton-test",
                ),
                (
                    "wine-test.tar.gz",
                    wine_digest,
                    wine_size,
                    wine_tmp,
                    "wine-test",
                ),
            ):
                relative = (
                    f"objects/sha256/{digest[:2]}/"
                    f"{digest[2:4]}/{digest}"
                )
                destination = immutable / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                source.replace(destination)
                objects.append(
                    {
                        "label": label,
                        "path": relative,
                        "role": "shared-runner",
                        "sha256": digest,
                        "size": size,
                    }
                )
                inventory.append(
                    {
                        "bytes": size,
                        "digest": f"sha256:{digest}",
                        "path": relative,
                    }
                )
                registrations.append(
                    {
                        "runner_id": runner_id,
                        "object_sha256": f"sha256:{digest}",
                        "acceptance_status": "not_tested",
                    }
                )

            write_json(collection / "INDEX.json", {"objects": objects})
            write_json(
                immutable / "VAULT_INVENTORY.json",
                {"objects": inventory},
            )
            write_json(
                collection / "COLLECTION_LAYOUT.json",
                {"registrations": registrations},
            )

            records, warnings = scan_runners(collection)
            self.assertEqual(warnings, ())
            self.assertEqual(len(records), 2)
            by_id = {record.runner_id: record for record in records}
            self.assertEqual(
                by_id["proton-test"].compatible_backends,
                ("umu",),
            )
            self.assertEqual(by_id["proton-test"].kind, "proton")
            self.assertEqual(
                by_id["wine-test"].compatible_backends,
                ("direct-wine", "bottles"),
            )
            self.assertEqual(by_id["wine-test"].kind, "wine")


if __name__ == "__main__":
    unittest.main()
