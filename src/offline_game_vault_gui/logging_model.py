from __future__ import annotations

from datetime import datetime
import re

from .model import LogRecord


FILTERS = (
    "TODOS",
    "ERROR",
    "WARNING",
    "INFO",
    "STDOUT",
    "STDERR",
)

_ERROR = re.compile(
    r"(?i)(?:\berror\b|\bfatal\b|traceback|exception)"
)
_WARNING = re.compile(
    r"(?i)(?:\bwarning\b|\bwarn\b)"
)


def make_record(
    message: str,
    *,
    stream: str = "internal",
    level: str | None = None,
) -> LogRecord:
    normalized_stream = stream.lower()
    if level is None:
        if _ERROR.search(message):
            level = "ERROR"
        elif _WARNING.search(message):
            level = "WARNING"
        elif normalized_stream == "stderr":
            level = "STDERR"
        elif normalized_stream == "stdout":
            level = "STDOUT"
        else:
            level = "INFO"
    return LogRecord(
        timestamp=datetime.now().astimezone().strftime(
            "%H:%M:%S"
        ),
        stream=normalized_stream,
        level=level.upper(),
        message=message.rstrip("\r\n"),
    )


def matches_filter(
    record: LogRecord,
    selected: str,
) -> bool:
    selected = selected.upper()
    return selected == "TODOS" or record.level == selected
