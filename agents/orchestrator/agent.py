from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

from uagents import Context

from core.acp import attach_chat, text_msg, turn_to_message
from core.audit import record_event
from core.bootstrap import make_agent
from core.calc import estimate_interest, get_effective_rules, pick_reconcile_mode
from core.cards import package_review
from core.guardrails import DRAFT_BANNER
from core.messages import (
    DraftRequest,
    DraftResponse,
    ReconcileRequest,
    ReconcileResponse,
)
from core.models import (
    Draft,
    Finding,
    InterestEstimate,
    ReconcileResult,
    Session,
    case_from_dict,
    session_from_dict,
    session_to_dict,
    to_dict,
)
from core.payment import attach_payment_protocol
from core.recovery import make_step_key, run_fallback_reconciliation
from core.state import Turn, _run_pipeline, handle_turn

TIMEOUT_SECONDS = 5.0

agent = make_agent(
    name="recoverpay-orchestrator",
    seed_env="ORCHESTRATOR_SEED",
    port=8000,
    description=(
        "RecoverPay orchestrator coordinates MSME overdue claims across specialist agents. "
        "Drafts for review only. Not legal advice. Never auto-sends messages."
    ),
)


def get_verifier_address() -> str | None:
    return os.getenv("VERIFIER_ADDRESS") or os.getenv("RECONCILER_ADDRESS")


def get_fallback_address() -> str | None:
    return os.getenv("FALLBACK_ADDRESS") or os.getenv("RECONCILER_LITE_ADDRESS")


def get_drafter_address() -> str | None:
    return os.getenv("DRAFTER_ADDRESS")


def _session(ctx: Context, sender: str) -> tuple[Session, dict]:
    store = ctx.storage.get("sessions") or {}
    session = session_from_dict(store.get(sender))
    if session.rules is None:
        session.rules = get_effective_rules()
    return session, store


def _save(ctx: Context, store: dict, sender: str, session: Session) -> None:
    store[sender] = session_to_dict(session)
    ctx.storage.set("sessions", store)


@agent.on_message(model=ReconcileResponse)
async def handle_reconcile_response(ctx: Context, sender: str, msg: ReconcileResponse) -> None:
    pending = ctx.storage.get("pending_requests") or {}
    req_info = pending.pop(msg.request_id, None)
    ctx.storage.set("pending_requests", pending)

    user_sender = req_info["user_sender"] if req_info else None
    if not user_sender:
        ctx.logger.warning("No pending request found for reconcile response %s", msg.request_id)
        return

    session, store = _session(ctx, user_sender)
    if session.case is None:
        return

    rec_inputs = {
        "mode": msg.mode,
        "invoice_no": session.case.invoice_no,
        "invoice_amount": session.case.invoice_amount,
    }
    rec_key = make_step_key(session.case.case_id, "reconcile", rec_inputs)
    if session.step_keys.get("reconcile") == rec_key and session.reconcile is not None:
        ctx.logger.info("Reconcile response already processed idempotently for %s", rec_key)
        return

    rec_data = msg.result or {}
    session.reconcile = ReconcileResult(
        mode=msg.mode,
        matched=bool(rec_data.get("matched", False)),
        evidence_complete=bool(rec_data.get("evidence_complete", False)),
        can_draft_payment_reminder=bool(rec_data.get("can_draft_payment_reminder", False)),
        findings=[Finding(**f) for f in rec_data.get("findings", [])],
        notes=msg.notes or rec_data.get("notes", ""),
    )
    session.step_keys["reconcile"] = rec_key
    record_event(
        session=session,
        step="reconcile",
        actor="verifier" if msg.mode == "full" else "fallback",
        action="execute",
        inputs=rec_inputs,
        outputs={
            "mode": msg.mode,
            "matched": session.reconcile.matched,
            "evidence_complete": session.reconcile.evidence_complete,
        },
        approval_status=None,
    )

    drafter_addr = get_drafter_address()
    if drafter_addr:
        session.estimate = estimate_interest(session.case, rules=session.rules)
        draft_req_id = uuid.uuid4().hex
        pending[draft_req_id] = {
            "request_id": draft_req_id,
            "user_sender": user_sender,
            "step": "draft",
            "created_at": time.time(),
            "retry_count": 0,
        }
        ctx.storage.set("pending_requests", pending)
        _save(ctx, store, user_sender, session)
        await ctx.send(
            drafter_addr,
            DraftRequest(
                request_id=draft_req_id,
                case=to_dict(session.case),
                estimate=to_dict(session.estimate),
                reconcile=to_dict(session.reconcile),
                sender_session_id=user_sender,
            ),
        )
        return

    turn = _run_pipeline(session)
    _save(ctx, store, user_sender, session)
    await ctx.send(user_sender, turn_to_message(turn))


@agent.on_message(model=DraftResponse)
async def handle_draft_response(ctx: Context, sender: str, msg: DraftResponse) -> None:
    pending = ctx.storage.get("pending_requests") or {}
    req_info = pending.pop(msg.request_id, None)
    ctx.storage.set("pending_requests", pending)

    user_sender = req_info["user_sender"] if req_info else None
    if not user_sender:
        return

    session, store = _session(ctx, user_sender)
    if session.case is None:
        return

    session.drafts = [Draft(**d) for d in msg.drafts]
    draft_inputs = {
        "interest": session.estimate.interest if session.estimate else 0,
        "reconcile_mode": session.reconcile.mode if session.reconcile else "",
        "can_draft_payment_reminder": session.reconcile.can_draft_payment_reminder if session.reconcile else False,
    }
    session.step_keys["draft"] = make_step_key(session.case.case_id, "draft", draft_inputs)
    record_event(
        session=session,
        step="draft",
        actor="drafter",
        action="execute",
        inputs=draft_inputs,
        outputs={"draft_count": len(session.drafts), "kinds": [d.kind for d in session.drafts]},
        approval_status=None,
    )
    session.stage = "review"
    _save(ctx, store, user_sender, session)

    drafts_text = "\n\n".join(f"[{d.kind}] {d.subject}\n{d.body}" for d in session.drafts)
    turn = Turn(
        text=(
            f"Drafter completed {len(session.drafts)} draft(s) (unsent for review).\n"
            f"Interest: {session.estimate.currency} {session.estimate.interest:.2f} ({session.estimate.label}).\n\n"
            f"{drafts_text}"
        ),
        card_kind="review",
        card_payload=package_review(session.case, session.estimate, session.reconcile, session.drafts),
    )
    await ctx.send(user_sender, turn_to_message(turn))


@agent.on_interval(period=1.0)
async def check_pending_timeouts(ctx: Context) -> None:
    pending = ctx.storage.get("pending_requests") or {}
    now = time.time()
    updated = False

    for req_id, info in list(pending.items()):
        elapsed = now - info.get("created_at", now)
        if elapsed > TIMEOUT_SECONDS:
            if info.get("retry_count", 0) < 1:
                info["retry_count"] = info.get("retry_count", 0) + 1
                info["created_at"] = now
                pending[req_id] = info
                updated = True
                ctx.logger.warning("Verifier timed out for %s. Retrying once...", req_id)
                if info.get("step") == "reconcile":
                    target = info.get("target_address")
                    req = ReconcileRequest(
                        request_id=req_id,
                        case=info.get("case", {}),
                        mode=info.get("mode", "full"),
                        sender_session_id=info.get("user_sender", ""),
                        retry_count=1,
                    )
                    if target:
                        await ctx.send(target, req)
            else:
                ctx.logger.error("Verifier timed out after 1 retry for %s. Asking fallback approval.", req_id)
                user_sender = info.get("user_sender")
                del pending[req_id]
                updated = True
                if user_sender:
                    session, store = _session(ctx, user_sender)
                    session.failed_step = "reconcile"
                    session.fallback_available = True
                    session.fallback_mode = "lite"
                    session.stage = "waiting_for_approval"
                    record_event(
                        session=session,
                        step="reconcile",
                        actor="verifier",
                        action="failed",
                        inputs={"mode": info.get("mode", "full")},
                        outputs={"error": "VerifierTimeout after 1 retry"},
                        approval_status="pending",
                    )
                    _save(ctx, store, user_sender, session)
                    await ctx.send(
                        user_sender,
                        text_msg(
                            "Verifier component timed out after 1 retry. The step has failed.\n\n"
                            "A rule-based fallback agent (mode \"lite\") can take over with fewer checks.\n"
                            "Do you approve running the fallback? Reply 'approve' to proceed, or 'refuse' to cancel."
                        ),
                    )
    if updated:
        ctx.storage.set("pending_requests", pending)


async def on_text(ctx: Context, sender: str, text: str) -> Turn:
    specialist_addrs = {
        get_verifier_address(),
        get_fallback_address(),
        get_drafter_address(),
    }
    if sender in specialist_addrs and sender is not None:
        ctx.logger.info("Specialist note from %s: %s", sender, text[:200])
        return Turn("Specialist update recorded. Drafts remain unsent.")

    session, store = _session(ctx, sender)
    verifier_addr = get_verifier_address()

    # If verifier agent address is configured and user is triggering case reconciliation
    if verifier_addr and session.stage in {"intake", "start", "work"} and "case" in text.lower():
        session, turn = handle_turn(session, text)
        if session.case and "reconcile" not in session.step_keys and session.stage != "blocked":
            req_id = uuid.uuid4().hex
            mode = pick_reconcile_mode(session.case)
            pending = ctx.storage.get("pending_requests") or {}
            pending[req_id] = {
                "request_id": req_id,
                "user_sender": sender,
                "step": "reconcile",
                "target_address": verifier_addr,
                "created_at": time.time(),
                "retry_count": 0,
                "case": to_dict(session.case),
                "mode": mode,
            }
            ctx.storage.set("pending_requests", pending)
            _save(ctx, store, sender, session)
            await ctx.send(
                verifier_addr,
                ReconcileRequest(
                    request_id=req_id,
                    case=to_dict(session.case),
                    mode=mode,
                    sender_session_id=sender,
                    retry_count=0,
                ),
            )
            return Turn(
                f"Case {session.case.case_id} loaded. Sent to Verifier agent ({verifier_addr}) "
                "for full evidence verification. Awaiting response..."
            )

    session, turn = handle_turn(session, text)
    _save(ctx, store, sender, session)
    return turn


attach_chat(agent, on_text)
attach_payment_protocol(agent, role="seller")


@agent.on_event("startup")
async def startup(ctx: Context) -> None:
    ctx.logger.info("RecoverPay orchestrator address: %s", agent.address)
    ctx.logger.info("Specialist agents:")
    ctx.logger.info("  Verifier: %s", get_verifier_address() or "(in-process / local)")
    ctx.logger.info("  Fallback: %s", get_fallback_address() or "(in-process / local)")
    ctx.logger.info("  Drafter:  %s", get_drafter_address() or "(in-process / local)")
    ctx.logger.info("Drafts for review only. Not legal advice. No auto-send.")


if __name__ == "__main__":
    agent.run()
