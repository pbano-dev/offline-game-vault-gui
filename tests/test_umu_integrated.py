from __future__ import annotations

import hashlib
import io
import json
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

from offline_game_vault_gui.umu_catalog import scan_umu_catalog
from offline_game_vault_gui.umu_model import (
    UmuBackendTemplate,
    UmuProfile,
    UmuRunner,
    UmuSelection,
)
from offline_game_vault_gui.umu_overlay import build_umu_overlay
from offline_game_vault_gui.umu_service import destination_name


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _runner_archive(path: Path, root: str) -> tuple[str, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w:gz") as archive:
        for name, payload, mode in (
            ("proton", b"#!/bin/sh\n", 0o755),
            ("files/bin/wine", b"wine\n", 0o755),
            ("files/bin/wineserver", b"wineserver\n", 0o755),
        ):
            info = tarfile.TarInfo(f"{root}/{name}")
            info.mode = mode
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest, path.stat().st_size


def _native_capsule() -> dict[str, object]:
    return {
        "schema": 0,
        "capsule_id": "steam-1-native",
        "game": {
            "title": "Native UMU",
            "appid": 1,
            "source_store": "Steam",
            "preserved_version": "1",
        },
        "objects": [
            {
                "id": "game",
                "digest": "sha256:" + "1" * 64,
                "archive_path": "objects/sha256/11/11/" + "1" * 64,
                "format": "tar",
                "size": 1,
                "roles": ["game_payload"],
            },
            {
                "id": "stack",
                "digest": "sha256:" + "2" * 64,
                "archive_path": "objects/sha256/22/22/" + "2" * 64,
                "format": "tar",
                "size": 1,
                "roles": ["runner", "runtime", "tool"],
            },
        ],
        "profiles": [
            {
                "id": "linux-umu-exact",
                "platform": "linux",
                "adapter": "umu",
                "status": "verified",
                "dependencies": ["game", "stack"],
                "launch": {
                    "entrypoint": "payload/game.exe",
                    "working_directory": "payload",
                    "arguments": [],
                    "network": "isolated",
                },
                "umu": {
                    "schema": 0,
                    "layout": [
                        {
                            "object": "game",
                            "source": "payload",
                            "destination": "payload",
                        },
                        {
                            "object": "stack",
                            "source": "engine",
                            "destination": "engine",
                        },
                    ],
                    "launchers": [],
                    "protected_manifests": [],
                    "symlink_manifests": [],
                    "state_archives": [],
                    "mutable_paths": [
                        "engine/proton/proton-test/files/steampipe_fixups_mtime"
                    ],
                    "paths": {
                        "launcher": "launchers/play.sh",
                        "sanitizer": "launchers/sanitize.sh",
                        "runtime_var": "engine/xdg-data/umu/steamrt3/var",
                    },
                },
            }
        ],
    }


def _wine_capsule() -> dict[str, object]:
    return {
        "schema": 0,
        "capsule_id": "steam-2-wine",
        "game": {
            "title": "Wine Source",
            "appid": 2,
            "source_store": "Steam",
            "preserved_version": "2",
        },
        "objects": [
            {
                "id": "game-prefix",
                "digest": "sha256:" + "3" * 64,
                "archive_path": "objects/sha256/33/33/" + "3" * 64,
                "format": "tar",
                "size": 1,
                "roles": ["game_payload", "prefix_baseline"],
            },
            {
                "id": "old-runner",
                "digest": "sha256:" + "4" * 64,
                "archive_path": "objects/sha256/44/44/" + "4" * 64,
                "format": "tar",
                "size": 1,
                "roles": ["runner"],
            },
        ],
        "profiles": [
            {
                "id": "linux-direct-wine",
                "platform": "linux",
                "adapter": "wine",
                "status": "not_tested",
                "dependencies": ["game-prefix", "old-runner"],
                "launch": {
                    "entrypoint": "prefix/drive_c/game/game.exe",
                    "working_directory": "prefix/drive_c/game",
                    "arguments": ["-windowed"],
                    "network": "host_default",
                },
                "playable": {
                    "schema": 0,
                    "backend": "wine",
                    "layout": [
                        {
                            "object": "game-prefix",
                            "source": "root",
                            "destination": "prefix",
                        },
                        {
                            "object": "old-runner",
                            "source": "Old",
                            "destination": "runner/Old",
                        },
                    ],
                    "paths": {
                        "prefix": "prefix",
                        "runner": "runner/Old",
                        "wine": "runner/Old/files/bin/wine",
                        "wineserver": "runner/Old/files/bin/wineserver",
                    },
                    "mutable_paths": ["prefix/system.reg"],
                    "nested_archives": [],
                    "allowed_absolute_symlinks": [],
                },
            }
        ],
    }


class UmuIntegratedCatalogTests(unittest.TestCase):
    def test_scans_native_and_convertible_profiles_and_filters_soda(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            immutable = root / "01_IMMUTABLE_VAULT"
            objects = immutable / "objects/sha256"

            candidate = root / "runner.tar.gz"
            digest, size = _runner_archive(candidate, "proton-test")
            stored = objects / digest[:2] / digest[2:4] / digest
            stored.parent.mkdir(parents=True)
            stored.write_bytes(candidate.read_bytes())

            _write_json(
                root / "INDEX.json",
                {
                    "capsules": [
                        {
                            "capsule_id": "steam-1-native",
                            "capsule": (
                                "02_CAPSULES/steam-1-native/capsule.json"
                            ),
                        },
                        {
                            "capsule_id": "steam-2-wine",
                            "capsule": (
                                "02_CAPSULES/steam-2-wine/capsule.json"
                            ),
                        },
                    ],
                    "objects": [
                        {
                            "role": "shared-runner",
                            "label": "proton-test.tar.gz",
                            "sha256": digest,
                            "path": (
                                f"objects/sha256/{digest[:2]}/"
                                f"{digest[2:4]}/{digest}"
                            ),
                            "size": size,
                        }
                    ],
                },
            )
            _write_json(
                immutable / "VAULT_INVENTORY.json",
                {
                    "objects": [
                        {
                            "digest": f"sha256:{digest}",
                            "path": (
                                f"objects/sha256/{digest[:2]}/"
                                f"{digest[2:4]}/{digest}"
                            ),
                            "bytes": size,
                        }
                    ]
                },
            )
            _write_json(
                root / "COLLECTION_LAYOUT.json",
                {
                    "registrations": [
                        {
                            "runner_id": "proton-test",
                            "object_sha256": f"sha256:{digest}",
                            "acceptance_status":
                                "not_tested_as_decoupled_runner",
                            "operation_id": "synthetic",
                        }
                    ]
                },
            )
            _write_json(
                root / "02_CAPSULES/steam-1-native/capsule.json",
                _native_capsule(),
            )
            _write_json(
                root / "02_CAPSULES/steam-2-wine/capsule.json",
                _wine_capsule(),
            )

            catalog = scan_umu_catalog(root)

            self.assertEqual(
                [item.runner_id for item in catalog.runners],
                ["proton-test"],
            )
            native = catalog.profiles_for_capsule("steam-1-native")
            self.assertEqual(
                [item.kind for item in native],
                ["native-exact", "native-modular"],
            )
            wine = catalog.profiles_for_capsule("steam-2-wine")
            self.assertEqual(
                [item.kind for item in wine],
                ["derived-wine"],
            )
            self.assertTrue(
                catalog.has_native_profiles("steam-1-native")
            )
            modular = native[1]
            self.assertEqual(
                [
                    item.runner_id
                    for item in catalog.compatible_runners(modular)
                ],
                ["proton-test"],
            )


class UmuOverlayTests(unittest.TestCase):
    def _runner(self, root: Path) -> UmuRunner:
        object_path = root / "runner.tar.gz"
        object_path.write_bytes(b"x")
        return UmuRunner(
            runner_id="proton-test",
            digest=hashlib.sha256(b"x").hexdigest(),
            size=1,
            archive_path="objects/sha256/aa/bb/digest",
            object_path=object_path,
            archive_format="tar.gz",
            source_root="Proton-Test",
            proton_path="proton",
            wine_path="files/bin/wine",
            wineserver_path="files/bin/wineserver",
            acceptance_status="not_tested_as_umu_runner",
        )

    def test_generic_overlay_uses_real_backend_partitions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capsule = _wine_capsule()
            capsule_path = root / "source/capsule.json"
            _write_json(capsule_path, capsule)
            native = _native_capsule()
            template_profile = native["profiles"][0]
            template_object = native["objects"][1]
            template = UmuBackendTemplate(
                capsule_path=capsule_path,
                capsule=native,
                profile_id="linux-umu-exact",
                composite_object_id="stack",
                composite_digest="2" * 64,
                composite_object=template_object,
                source_mapping={
                    "object": "stack",
                    "source": "engine",
                    "destination": "engine",
                },
                runtime_var="engine/xdg-data/umu/steamrt3/var",
            )
            profile = UmuProfile(
                capsule_id="steam-2-wine",
                title="Wine Source",
                preserved_version="2",
                capsule_path=capsule_path,
                profile_id="linux-direct-wine-umu-candidate",
                profile_status="candidate",
                kind="derived-wine",
                source_profile_id="linux-direct-wine",
                state_root=None,
                state_archives=(),
                original_profile=capsule["profiles"][0],
                capsule=capsule,
                backend_template=template,
            )
            runner = self._runner(root)
            selection = UmuSelection(
                collection_root=root,
                immutable_vault_root=root,
                profile=profile,
                runner=runner,
                destination=root / "destination",
                save_id=None,
            )

            generated = build_umu_overlay(
                selection,
                root / "overlay",
            )
            document = json.loads(generated.capsule_path.read_text(encoding="utf-8"))
            derived = document["profiles"][0]
            layout = derived["umu"]["layout"]
            sources = {item["source"] for item in layout}
            self.assertIn("engine/python-portable", sources)
            self.assertIn("engine/umu-portable", sources)
            self.assertIn("engine/xdg-data", sources)
            self.assertNotIn("engine", sources)
            self.assertNotIn("old-runner", derived["dependencies"])
            self.assertEqual(
                derived["launch"]["network"],
                "host_default",
            )
            launcher = root / "overlay/launchers/JUGAR_UMU_CANDIDATO.sh"
            syntax = subprocess.run(
                ["bash", "-n", str(launcher)],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertEqual(syntax.returncode, 0, syntax.stderr)

    def test_destination_distinguishes_profile_runner_and_save(self) -> None:
        name = destination_name(
            capsule_id="steam-2-wine",
            profile_id="profile",
            runner_id="proton-test",
            save_id=None,
        )
        self.assertIn("steam-2-wine--umu--profile--proton-test", name)


if __name__ == "__main__":
    unittest.main()
