from __future__ import annotations

from datetime import datetime, timezone

from .model import LogRecord


def make_record(
    message: str,
    *,
    stream: str = "internal",
    level: str | None = None,
) -> LogRecord:
    effective = level or (
        "ERROR" if stream == "stderr" else "INFO"
    )
    return LogRecord(
        timestamp=datetime.now(timezone.utc).isoformat(),
        stream=stream,
        level=effective,
        message=message,
    )
