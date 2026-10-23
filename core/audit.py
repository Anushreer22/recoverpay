from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AUDIT_LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "audit_events.jsonl"
_AUDIT_MEMORY_LOG: list[dict[str, Any]] = []

SECRET_KEYWORDS = ("secret", "token", "password", "auth", "seed", "api_key", "credential", "private")


def _sanitize_secrets(obj: Any) -> Any:
    """Recursively redacts secrets and truncates verbose structures to protect confidentiality."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        sanitized = {}
        for k, v in obj.items():
            if any(s in str(k).lower() for s in SECRET_KEYWORDS):
                sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = _sanitize_secrets(v)
        return sanitized
    if isinstance(obj, list):
        return [_sanitize_secrets(v) for v in obj[:10]]
    if isinstance(obj, str):
        if len(obj) > 250:
            return obj[:240] + "...[truncated]"
        return obj
    if hasattr(obj, "__dataclass_fields__"):
        from core.models import to_dict
        return _sanitize_secrets(to_dict(obj))
    return obj


def record_event(
    session: Any,
    step: str,
    actor: str,
    action: str,
    inputs: Any = None,
    outputs: Any = None,
    rules_used: list[dict[str, Any]] | None = None,
    approval_status: str | None = None,
    log_to_file: bool = False,
) -> dict[str, Any]:
    """Records an append-only audit event in the session with secrets redacted."""
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "step": str(step),
        "actor": str(actor),
        "action": str(action),
        "inputs": _sanitize_secrets(inputs),
        "outputs": _sanitize_secrets(outputs),
        "rules_used": rules_used or [],
        "approval_status": str(approval_status) if approval_status is not None else None,
    }

    if hasattr(session, "audit_events") and isinstance(session.audit_events, list):
        session.audit_events.append(event)

    _AUDIT_MEMORY_LOG.append(event)

    if log_to_file:
        try:
            AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(event) + "\n")
        except Exception:
            pass

    return event


def record_audit_event(
    event_type: str,
    payload: dict[str, Any] | None = None,
    log_path: Path | None = None,
) -> dict[str, Any]:
    """Backwards-compatible helper recording to memory/log."""
    payload = payload or {}
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "step": str(payload.get("step") or event_type),
        "actor": str(payload.get("actor") or "system"),
        "action": event_type,
        "inputs": _sanitize_secrets(payload.get("inputs") or {}),
        "outputs": _sanitize_secrets(payload.get("outputs") or payload),
        "rules_used": payload.get("rules_used") or [],
        "approval_status": str(payload.get("approval_status")) if "approval_status" in payload else None,
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


def render_audit_trail(session: Any) -> str:
    """Renders the session audit trail as a short readable summary."""
    events = session.audit_events if hasattr(session, "audit_events") else session
    if not events:
        return "Audit trail is empty."
    lines = ["Audit Trail Summary:"]
    for i, e in enumerate(events, 1):
        ts = e.get("timestamp", "")
        step = e.get("step", "unknown")
        actor = e.get("actor", "system")
        act = e.get("action", "unknown")
        appr = e.get("approval_status") or "n/a"
        lines.append(f"{i}. [{ts}] Step: {step} | Actor: {actor} | Action: {act} | Approval: {appr}")
        if e.get("rules_used"):
            rules_str = ", ".join(
                f"{r.get('key', '')} ({r.get('source', '')})"
                if isinstance(r, dict)
                else str(r)
                for r in e["rules_used"]
            )
            lines.append(f"   Rules: {rules_str}")
        if e.get("outputs"):
            out_str = str(e["outputs"])
            if len(out_str) > 100:
                out_str = out_str[:97] + "..."
            lines.append(f"   Outputs: {out_str}")
    return "\n".join(lines)


def get_audit_events(event_type: str | None = None) -> list[dict[str, Any]]:
    if event_type:
        return [e for e in _AUDIT_MEMORY_LOG if e.get("action") == event_type or e.get("step") == event_type]
    return list(_AUDIT_MEMORY_LOG)


def clear_audit_events() -> None:
    _AUDIT_MEMORY_LOG.clear()
