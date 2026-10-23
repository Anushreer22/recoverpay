from __future__ import annotations

from typing import Any
from uagents import Model


class ReconcileRequest(Model):
    """Request sent by orchestrator to verifier or fallback agent to reconcile a case."""
    request_id: str = ""
    case: dict[str, Any] = {}
    mode: str = "full"
    sender_session_id: str = ""
    retry_count: int = 0


class ReconcileResponse(Model):
    """Response returned by verifier or fallback agent containing reconciliation results."""
    request_id: str = ""
    case_id: str = ""
    mode: str = "full"
    result: dict[str, Any] = {}
    notes: str = ""
    error: str | None = None


class DraftRequest(Model):
    """Request sent by orchestrator to drafter agent to draft factual notices."""
    request_id: str = ""
    case: dict[str, Any] = {}
    estimate: dict[str, Any] = {}
    reconcile: dict[str, Any] = {}
    sender_session_id: str = ""


class DraftResponse(Model):
    """Response returned by drafter agent containing prepared drafts."""
    request_id: str = ""
    case_id: str = ""
    drafts: list[dict[str, Any]] = []
    used_fallback_llm: bool = False
    error: str | None = None

