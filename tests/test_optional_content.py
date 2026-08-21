from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

from offline_game_vault_gui.core import CoreClient
from offline_game_vault_gui.model import CompositionRequest


RESULT = {
    "schema": 0,
    "capsule_id": "example-game",
    "backend": "direct-wine",
    "runner_id": "runner",
    "profile_id": "game-source",
    "destination": "/derived/example",
    "materialized": True,
    "played": False,
    "play_complete": None,
    "backend_result": {},
}


class OptionalContentGuiTests(unittest.TestCase):
    def client(self) -> CoreClient:
        return CoreClient(
            command=("ogv",),
            environment={},
            description="test",
        )

    def test_catalog_is_read_from_core_without_gui_inference(self) -> None:
        payload = {
            "schema": 0,
            "capsule": "/collection/02_CAPSULES/example/capsule.json",
            "items": [
                {
                    "id": "manual",
                    "object_id": "optional-manual",
                    "classification": "manual",
                    "description": "Manual",
                    "source": "manual",
                    "placement": {
                        "mode": "sidecar",
                        "destination": "manual",
                    },
                    "digest": "sha256:" + "1" * 64,
                    "format": "tar.gz",
                    "size": 100,
                    "object_present": True,
                    "manifest_present": True,
                    "manifest_sidecar_present": True,
                    "available": True,
                },
                {
                    "id": "dlc",
                    "object_id": "optional-dlc",
                    "classification": "dlc",
                    "description": "",
                    "source": "dlc",
                    "placement": {
                        "mode": "game-overlay",
                        "destination": "DLC",
                    },
                    "digest": "sha256:" + "2" * 64,
                    "format": "tar.gz",
                    "size": 200,
                    "object_present": False,
                    "manifest_present": False,
                    "manifest_sidecar_present": False,
                    "available": False,
                },
            ],
        }
        client = self.client()
        with patch.object(
            CoreClient,
            "run_json",
            return_value=payload,
        ) as run_json:
            items = client.list_optional_content(
                Path("/collection"),
                Path("/collection/02_CAPSULES/example/capsule.json"),
            )

        arguments = run_json.call_args.args[0]
        self.assertEqual(arguments[0], "list-optional-content")
        self.assertIn("--collection-root", arguments)
        self.assertIn("--capsule", arguments)
        self.assertEqual([item["id"] for item in items], ["manual", "dlc"])
        self.assertTrue(items[0]["available"])
        self.assertFalse(items[1]["available"])
        self.assertEqual(
            items[1]["placement"],
            {"mode": "game-overlay", "destination": "DLC"},
        )

    def test_compose_forwards_every_selected_id_once(self) -> None:
        request = CompositionRequest(
            collection_root=Path("/collection"),
            capsule_path=Path("/collection/capsule.json"),
            backend="direct-wine",
            runner_id="runner",
            destination=Path("/derived/example"),
            content_ids=("manual", "dlc"),
        )
        with patch.object(
            CoreClient,
            "run_json",
            return_value=RESULT,
        ) as run_json:
            self.client().compose(request)

        arguments = run_json.call_args.args[0]
        self.assertEqual(arguments.count("--content-id"), 2)
        first = arguments.index("--content-id")
        second = arguments.index("--content-id", first + 1)
        self.assertEqual(arguments[first + 1], "manual")
        self.assertEqual(arguments[second + 1], "dlc")

    def test_request_model_is_backend_neutral(self) -> None:
        for backend in ("bottles", "direct-wine", "umu"):
            with self.subTest(backend=backend):
                request = CompositionRequest(
                    collection_root=Path("/collection"),
                    capsule_path=Path("/collection/capsule.json"),
                    backend=backend,
                    runner_id="runner",
                    content_ids=("manual",),
                )
                self.assertEqual(request.content_ids, ("manual",))

    def test_presentation_consumes_core_records_only(self) -> None:
        app = Path(
            "src/offline_game_vault_gui/app.py"
        ).read_text(encoding="utf-8")
        service = Path(
            "src/offline_game_vault_gui/service.py"
        ).read_text(encoding="utf-8")

        for token in (
            "QListWidget",
            "Optional content",
            "def _load_optional_content",
            "self.service.optional_content(",
            'record.get("available")',
            "Qt.ItemFlag.ItemIsUserCheckable",
            "content_ids=self._selected_content_ids()",
        ):
            self.assertIn(token, app)

        self.assertIn(
            "return self.core.list_optional_content(root, capsule)",
            service,
        )
        self.assertNotIn('if mode == "game-overlay"', app)
        self.assertNotIn('if mode == "sidecar"', app)


if __name__ == "__main__":
    unittest.main()
