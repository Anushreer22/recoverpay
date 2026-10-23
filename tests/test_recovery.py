from __future__ import annotations

import ast
import os
from pathlib import Path
import pytest

from core.audit import record_event, render_audit_trail
from core.calc import estimate_interest, reconcile_case
from core.models import Session, session_from_dict, session_to_dict
from core.recovery import (
    FlakyReconciler,
    InProcessReconciler,
    ReconcilerClient,
    ReconcilerTimeout,
    make_step_key,
    run_fallback_reconciliation,
)
from core.state import handle_turn, load_case

# TEST ONLY, not legal values
TEST_RULES = {
    "_note": "TEST ONLY, not legal values",
    "max_credit_days": {"value": 45, "source": "fake-statute-sec-99", "verified": True},
    "default_credit_days": {"value": 15, "source": "fake-statute-sec-99", "verified": True},
    "interest_multiplier": {"value": 3.0, "source": "fake-statute-sec-99", "verified": True},
    "compounding_basis": {"value": "monthly", "source": "fake-statute-sec-99", "verified": True},
    "day_count_month": {"value": 30, "source": "fake-statute-sec-99", "verified": True},
    "rbi_bank_rate": {"value": 0.065, "source": "fake-rbi-notice-00", "verified": True},
    "rbi_bank_rate_as_of": {"value": "2025-06-06", "source": "fake-rbi-notice-00", "verified": True},
    "eligible_classes": {"value": ["micro", "small"], "source": "fake-statute-sec-99", "verified": True},
    "ineligible_activities": {"value": ["trading"], "source": "fake-statute-sec-99", "verified": True},
    "ineligible_nic_prefixes": {"value": ["45", "46", "47"], "source": "fake-statute-sec-99", "verified": True},
    "registration_required": {"value": True, "source": "fake-statute-sec-99", "verified": True},
    "disclaimer": {"value": "Test disclaimer", "source": "fake-statute-sec-99", "verified": True},
    "forbidden_draft_terms": {"value": ["legal action", "we will sue"], "source": "fake-statute-sec-99", "verified": True},
}


def _setup_intake_session() -> Session:
    session = Session(rules=TEST_RULES)
    session, _ = handle_turn(session, "hi")
    session, _ = handle_turn(
        session,
        '{"action":"eligibility","registered":"yes","enterprise_class":"small","activity":"manufacturing"}',
    )
    assert session.stage == "intake"
    return session


def test_timeout_then_retry_then_fail():
    """Verify reconciler times out, retries once, marks step failed, and sets waiting-for-approval."""
    session = _setup_intake_session()
    reconciler = FlakyReconciler(force_fail=True)

    session, turn = handle_turn(session, "case1_clean", reconciler=reconciler)

    assert session.stage == "waiting_for_approval"
    assert session.failed_step == "reconcile"
    assert session.fallback_available is True
    assert "timed out after 1 retry" in turn.text
    assert "reconciler component timed out" in turn.text.lower()
    assert "rule-based fallback (mode \"lite\")" in turn.text
    assert "fewer checks" in turn.text

    # Verify failed audit event recorded
    failed_events = [e for e in session.audit_events if e["step"] == "reconcile" and e["action"] == "failed"]
    assert len(failed_events) == 1
    assert failed_events[0]["approval_status"] == "pending"


def test_swap_approved_resumes_without_rerunning_done_steps():
    """Verify approving fallback executes lite mode and resumes without re-running done steps."""
    session = _setup_intake_session()
    reconciler = FlakyReconciler(force_fail=True)

    session, _ = handle_turn(session, "case1_clean", reconciler=reconciler)
    assert session.stage == "waiting_for_approval"

    # User approves fallback
    session, turn = handle_turn(session, "approve")

    assert session.stage == "review"
    assert session.reconcile is not None
    assert session.reconcile.mode == "lite"
    assert session.estimate is not None
    assert session.drafts

    # Verify approval event was recorded
    approval_events = [
        e for e in session.audit_events if e["step"] == "fallback_approval" and e["action"] == "approval"
    ]
    assert len(approval_events) == 1
    assert approval_events[0]["approval_status"] == "approved"
    assert approval_events[0]["actor"] == "user"

    # Verify reconcile step key is saved
    assert "reconcile" in session.step_keys
    assert "estimate" in session.step_keys
    assert "draft" in session.step_keys


def test_swap_refused_ends_safely():
    """Verify refusing fallback ends the session safely with a clear message and refusal event."""
    session = _setup_intake_session()
    reconciler = FlakyReconciler(force_fail=True)

    session, _ = handle_turn(session, "case1_clean", reconciler=reconciler)
    assert session.stage == "waiting_for_approval"

    session, turn = handle_turn(session, "refuse")

    assert session.stage == "ended"
    assert "session ended" in turn.text.lower()
    assert "fallback was refused" in turn.text.lower()

    # Reconcile, estimate, and drafts should not have been finalized
    assert session.reconcile is None
    assert session.estimate is None

    # Refusal audit event recorded
    refusal_events = [
        e for e in session.audit_events if e["step"] == "fallback_approval" and e["action"] == "approval"
    ]
    assert len(refusal_events) == 1
    assert refusal_events[0]["approval_status"] == "refused"
    assert refusal_events[0]["actor"] == "user"


def test_restart_mid_workflow_then_resume():
    """Verify session serialized mid-workflow resumes from checkpoint without re-running done steps."""
    session = _setup_intake_session()
    reconciler = InProcessReconciler()

    session, _ = handle_turn(session, "case1_clean", reconciler=reconciler)
    assert session.stage == "review"
    assert "reconcile" in session.step_keys
    assert "estimate" in session.step_keys

    # Save and restore mid-workflow
    data = session_to_dict(session)
    restored = session_from_dict(data)

    assert restored.stage == "review"
    assert restored.step_keys == session.step_keys
    assert restored.reconcile.mode == session.reconcile.mode

    # Resume turn: keep package (finalization approval)
    restored, turn = handle_turn(restored, '{"action":"keep_package"}')
    assert restored.stage == "done"
    assert "kept for the supplier's review" in turn.text.lower()

    # Finalize draft approval event recorded
    final_events = [e for e in restored.audit_events if e["step"] == "finalize_draft"]
    assert len(final_events) == 1
    assert final_events[0]["approval_status"] == "approved"


def test_duplicate_message_delivery_does_not_rerun_or_duplicate_audit():
    """Verify duplicate message delivery does not re-run steps or duplicate audit events."""
    session = _setup_intake_session()
    reconciler = InProcessReconciler()

    session, _ = handle_turn(session, "case1_clean", reconciler=reconciler)
    assert session.stage == "review"

    # Count audit events per step
    reconcile_events_before = len([e for e in session.audit_events if e["step"] == "reconcile"])
    estimate_events_before = len([e for e in session.audit_events if e["step"] == "estimate"])
    draft_events_before = len([e for e in session.audit_events if e["step"] == "draft"])

    # Duplicate delivery of same case load command
    session, _ = handle_turn(session, "case1_clean", reconciler=reconciler)

    reconcile_events_after = len([e for e in session.audit_events if e["step"] == "reconcile"])
    estimate_events_after = len([e for e in session.audit_events if e["step"] == "estimate"])
    draft_events_after = len([e for e in session.audit_events if e["step"] == "draft"])

    assert reconcile_events_after == reconcile_events_before
    assert estimate_events_after == estimate_events_before
    assert draft_events_after == draft_events_before


def test_fallback_result_carries_note_of_fewer_checks():
    """Verify fallback reconciliation result explicitly carries a note of fewer checks."""
    case = load_case("case1_clean")
    fallback_res = run_fallback_reconciliation(case)

    assert fallback_res.mode == "lite"
    has_fewer_checks_note = "fewer checks" in fallback_res.notes.lower() or any(
        "fewer checks" in f.message.lower() for f in fallback_res.findings
    )
    assert has_fewer_checks_note


def test_approval_gate_finalizing_draft():
    """Verify finalizing a draft records an approval event with status approved."""
    session = _setup_intake_session()
    session, _ = handle_turn(session, "case1_clean")
    assert session.stage == "review"

    session, turn = handle_turn(session, '{"action":"keep_package"}')
    assert session.stage == "done"

    finalize_events = [
        e for e in session.audit_events if e["step"] == "finalize_draft" and e["action"] == "approval"
    ]
    assert len(finalize_events) == 1
    assert finalize_events[0]["approval_status"] == "approved"
    assert finalize_events[0]["actor"] == "user"


def test_audit_trail_rendering_and_no_secrets():
    """Verify render_audit_trail formats a readable summary and redacts secrets."""
    session = Session(rules=TEST_RULES)
    record_event(
        session=session,
        step="test_step",
        actor="system",
        action="execute",
        inputs={"api_key": "super_secret_123", "normal_data": "abc"},
        outputs={"token": "secret_token_456", "result": 42},
        approval_status="approved",
    )

    summary = render_audit_trail(session)
    assert "Audit Trail Summary:" in summary
    assert "Step: test_step" in summary
    assert "Approval: approved" in summary

    # Secrets must NEVER be in stored event or summary
    assert "super_secret_123" not in summary
    assert "secret_token_456" not in summary
    assert "[REDACTED]" in str(session.audit_events[0]["inputs"])
    assert "[REDACTED]" in str(session.audit_events[0]["outputs"])


def test_no_external_sending_or_filing_code():
    """Verify the codebase contains NO code that sends messages externally (smtp, requests.post to non-ASI endpoints)."""
    root_dir = Path(__file__).resolve().parent.parent
    prohibited_modules = {"smtplib", "urllib.request", "ftplib", "telnetlib"}

    checked_files = 0
    for target_dir in ["core", "agents"]:
        dir_path = root_dir / target_dir
        for py_path in dir_path.rglob("*.py"):
            checked_files += 1
            source = py_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_path))

            # 1. Check imports for smtplib and prohibited network modules
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert alias.name not in prohibited_modules, f"Forbidden import '{alias.name}' in {py_path}"
                elif isinstance(node, ast.ImportFrom):
                    assert node.module not in prohibited_modules, f"Forbidden import from '{node.module}' in {py_path}"

            # 2. Check for requests.post calls: only allowed to ASI endpoints in core/llm.py
            if "requests.post" in source:
                # Only core/llm.py is permitted to call requests.post, and it must target ASI endpoints
                assert py_path.name == "llm.py", f"Unexpected requests.post in {py_path}"
                assert "api.asi1.ai" in source or "ASI1_BASE_URL" in source

            # 3. Check for smtp mentions
            assert "smtp" not in source.lower(), f"Suspicious SMTP reference in {py_path}"

    assert checked_files > 5, "Scanner must check core and agent python files."


# =============================================================================
# MULTI-AGENT UAGENTS AND ACP TESTS (OFFLINE / FAKE SENDERS)
# =============================================================================

import time
from typing import Any
from agents.drafter.agent import handle_draft_request as drafter_handle_draft
from agents.fallback.agent import handle_reconcile_request as fallback_handle_reconcile
from agents.orchestrator.agent import (
    check_pending_timeouts,
    handle_reconcile_response as orch_handle_reconcile_resp,
)
from agents.verifier.agent import handle_reconcile_request as verifier_handle_reconcile
from core.llm import build_drafts_with_status, explain_evidence_gaps, parse_case_with_asi1
from core.messages import DraftRequest, DraftResponse, ReconcileRequest, ReconcileResponse
from core.models import to_dict


class MockStorage(dict):
    def get(self, key: str, default: Any = None) -> Any:
        return super().get(key, default)

    def set(self, key: str, value: Any) -> None:
        self[key] = value


class MockContext:
    def __init__(self, agent_address: str = "agent1_mock"):
        self.storage = MockStorage()
        self.sent_messages: list[tuple[str, Any]] = []
        self.agent = type("MockAgent", (), {"address": agent_address})()
        self.logger = type(
            "MockLogger",
            (),
            {
                "info": lambda *a, **k: None,
                "warning": lambda *a, **k: None,
                "error": lambda *a, **k: None,
            },
        )()

    async def send(self, destination: str, message: Any) -> None:
        self.sent_messages.append((destination, message))


@pytest.mark.asyncio
async def test_verifier_agent_force_fail_never_replies():
    """Verify Verifier agent never replies when FORCE_FAIL=true."""
    os.environ["FORCE_FAIL"] = "true"
    try:
        ctx = MockContext()
        case = load_case("case1_clean")
        req = ReconcileRequest(request_id="r1", case=to_dict(case), mode="full")
        await verifier_handle_reconcile(ctx, "agent1_sender", req)
        assert len(ctx.sent_messages) == 0
    finally:
        os.environ.pop("FORCE_FAIL", None)


@pytest.mark.asyncio
async def test_verifier_agent_normal_replies_with_result():
    """Verify Verifier agent returns full evidence reconciliation result when FORCE_FAIL=false."""
    os.environ["FORCE_FAIL"] = "false"
    try:
        ctx = MockContext()
        case = load_case("case1_clean")
        req = ReconcileRequest(request_id="r2", case=to_dict(case), mode="full")
        await verifier_handle_reconcile(ctx, "agent1_sender", req)
        assert len(ctx.sent_messages) == 1
        dest, resp = ctx.sent_messages[0]
        assert dest == "agent1_sender"
        assert isinstance(resp, ReconcileResponse)
        assert resp.mode == "full"
        assert resp.result["matched"] is True
    finally:
        os.environ.pop("FORCE_FAIL", None)


@pytest.mark.asyncio
async def test_fallback_agent_replies_with_fewer_checks():
    """Verify Fallback agent executes mode lite and notes fewer checks."""
    ctx = MockContext()
    case = load_case("case1_clean")
    req = ReconcileRequest(request_id="r3", case=to_dict(case), mode="lite")
    await fallback_handle_reconcile(ctx, "agent1_sender", req)
    assert len(ctx.sent_messages) == 1
    dest, resp = ctx.sent_messages[0]
    assert dest == "agent1_sender"
    assert isinstance(resp, ReconcileResponse)
    assert resp.mode == "lite"
    assert "fewer checks" in resp.notes.lower()


@pytest.mark.asyncio
async def test_drafter_agent_replies_with_draft_response():
    """Verify Drafter agent prepares drafts and replies with DraftResponse."""
    ctx = MockContext()
    case = load_case("case1_clean")
    req = DraftRequest(
        request_id="d1",
        case=to_dict(case),
        estimate={
            "principal": 100000.0,
            "currency": "INR",
            "interest": 100.0,
            "label": "Estimate, verify before use",
            "due_date": "2024-02-15",
            "as_of": "2024-03-01",
            "overdue_days": 15,
            "rbi_bank_rate": 0.065,
            "rbi_bank_rate_as_of": "2024-01-01",
            "annual_rate": 0.195,
            "total": 100100.0,
            "method": "test",
        },
        reconcile={
            "mode": "full",
            "matched": True,
            "evidence_complete": True,
            "can_draft_payment_reminder": True,
            "findings": [],
        },
        sender_session_id="user_123",
    )
    await drafter_handle_draft(ctx, "agent1_orchestrator", req)
    assert len(ctx.sent_messages) == 1
    dest, resp = ctx.sent_messages[0]
    assert dest == "agent1_orchestrator"
    assert isinstance(resp, DraftResponse)
    assert len(resp.drafts) > 0


@pytest.mark.asyncio
async def test_orchestrator_timeout_and_retry_on_interval():
    """Verify orchestrator checks pending requests, retries once on timeout, then prompts for fallback."""
    ctx = MockContext()
    user_sender = "user_456"
    session = _setup_intake_session()
    session.case = load_case("case1_clean")
    session.stage = "work"
    ctx.storage.set("sessions", {user_sender: session_to_dict(session)})

    now = time.time()
    ctx.storage.set(
        "pending_requests",
        {
            "req_timeout_1": {
                "request_id": "req_timeout_1",
                "user_sender": user_sender,
                "step": "reconcile",
                "target_address": "agent1_verifier",
                "created_at": now - 10.0,
                "retry_count": 0,
                "mode": "full",
                "case": to_dict(session.case),
            }
        },
    )

    # 1st tick: elapsed > 5s and retry_count == 0 -> retries once
    await check_pending_timeouts(ctx)
    pending = ctx.storage.get("pending_requests")
    assert "req_timeout_1" in pending
    assert pending["req_timeout_1"]["retry_count"] == 1
    assert len(ctx.sent_messages) == 1
    dest, sent_req = ctx.sent_messages[0]
    assert dest == "agent1_verifier"
    assert sent_req.retry_count == 1

    # Advance time past 5s again
    pending["req_timeout_1"]["created_at"] = time.time() - 10.0
    ctx.storage.set("pending_requests", pending)

    # 2nd tick: elapsed > 5s and retry_count >= 1 -> marks failed and asks for fallback approval
    await check_pending_timeouts(ctx)
    pending_after = ctx.storage.get("pending_requests")
    assert "req_timeout_1" not in pending_after

    saved_session = session_from_dict(ctx.storage.get("sessions")[user_sender])
    assert saved_session.stage == "waiting_for_approval"
    assert saved_session.failed_step == "reconcile"
    assert saved_session.fallback_available is True

    # User notified in chat
    assert len(ctx.sent_messages) == 2
    chat_dest, chat_msg = ctx.sent_messages[1]
    assert chat_dest == user_sender
    assert "timed out after 1 retry" in chat_msg.text().lower()
    assert "rule-based fallback" in chat_msg.text().lower()


@pytest.mark.asyncio
async def test_orchestrator_duplicate_reconcile_response_idempotency():
    """Verify duplicate reconcile response delivery does not rerun steps or duplicate audit events."""
    ctx = MockContext()
    user_sender = "user_789"
    session = _setup_intake_session()
    session.case = load_case("case1_clean")
    session.stage = "work"
    ctx.storage.set("sessions", {user_sender: session_to_dict(session)})

    ctx.storage.set(
        "pending_requests",
        {
            "req_dup": {
                "request_id": "req_dup",
                "user_sender": user_sender,
                "step": "reconcile",
            }
        },
    )

    resp = ReconcileResponse(
        request_id="req_dup",
        case_id="case1_clean",
        mode="full",
        result={
            "matched": True,
            "evidence_complete": True,
            "can_draft_payment_reminder": True,
            "findings": [],
        },
    )

    # First delivery
    await orch_handle_reconcile_resp(ctx, "agent1_verifier", resp)
    session_after_first = session_from_dict(ctx.storage.get("sessions")[user_sender])
    assert "reconcile" in session_after_first.step_keys
    rec_events_1 = [e for e in session_after_first.audit_events if e["step"] == "reconcile"]
    assert len(rec_events_1) == 1

    # Second delivery
    ctx.storage.set("pending_requests", {"req_dup": {"request_id": "req_dup", "user_sender": user_sender}})
    await orch_handle_reconcile_resp(ctx, "agent1_verifier", resp)
    session_after_second = session_from_dict(ctx.storage.get("sessions")[user_sender])
    rec_events_2 = [e for e in session_after_second.audit_events if e["step"] == "reconcile"]
    assert len(rec_events_2) == 1


def test_asi1_live_path_fallback_behavior(monkeypatch):
    """Verify ASI1 live path functions gracefully fall back when API key is missing or fails."""
    monkeypatch.delenv("ASI1_API_KEY", raising=False)
    monkeypatch.delenv("ASI_ONE_API_KEY", raising=False)
    case = load_case("case2_po_mismatch")
    rec = reconcile_case(case, mode="full")

    # 1. explain_evidence_gaps falls back to template findings when no ASI1 key
    explanation, used_asi1 = explain_evidence_gaps(rec.findings, case)
    assert used_asi1 is False
    assert "po amount" in explanation.lower() or "qty" in explanation.lower()

    # 2. parse_case_with_asi1 returns (None, False) when no API key is available
    parsed_case, parsed_used_asi1 = parse_case_with_asi1("Random free text invoice 100")
    assert parsed_used_asi1 is False

    # 3. build_drafts_with_status returns template drafts and used_asi1=False when ASI1 unavailable
    est = estimate_interest(case, rules=TEST_RULES)
    drafts, draft_used_asi1 = build_drafts_with_status(case, est, rec, rules=TEST_RULES, use_llm=True)
    assert draft_used_asi1 is False
    assert len(drafts) > 0
    assert all("draft for review" in d.body.lower() for d in drafts)


