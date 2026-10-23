from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AUDIT_LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "audit_events.jsonl"
_AUDIT_MEMORY_LOG: list[dict[str, Any]] = []


def record_audit_event(
    event_type: str,
    payload: dict[str, Any] | None = None,
    log_path: Path | None = None,
) -> dict[str, Any]:
    """Records an audit event to the in-memory log and persistent jsonl log."""
    event = {
        "event": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload or {},
    }
    _AUDIT_MEMORY_LOG.append(event)
    target = log_path or AUDIT_LOG_PATH
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
    except Exception:
        pass
    return event


def get_audit_events(event_type: str | None = None) -> list[dict[str, Any]]:
    """Returns recorded audit events, optionally filtered by event type."""
    if event_type:
        return [e for e in _AUDIT_MEMORY_LOG if e.get("event") == event_type]
    return list(_AUDIT_MEMORY_LOG)


def clear_audit_events() -> None:
    """Clears the in-memory audit log (useful for tests)."""
    _AUDIT_MEMORY_LOG.clear()

