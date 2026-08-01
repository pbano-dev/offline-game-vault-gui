from __future__ import annotations

from pathlib import Path

from .model import MaterializationRequest


BASE_RECEIPT_NAME = "materialization-receipt.json"
PLAYABLE_RECEIPT_NAME = "playable-materialization.json"


class GuardError(RuntimeError):
    pass


def validate_request(request: MaterializationRequest) -> MaterializationRequest:
    root = request.collection_root.resolve(strict=True)
    try:
        request.destination.resolve(strict=False).relative_to(root)
    except ValueError:
        return request
    raise GuardError("Destination must be outside the collection")
