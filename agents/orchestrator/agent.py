from __future__ import annotations

import json
import os
from typing import Any

from uagents import Context

from core.acp import attach_chat, text_msg
from core.audit import get_audit_events, record_audit_event
from core.bootstrap import make_agent
from core.models import session_from_dict, session_to_dict, to_dict
from core.planner import Planner, get_recommended_steps
from core.readiness import (
    CHECKLIST_LABEL,
    ConsentRequired,
    Profile,
    ReadinessResult,
    SchemeRulesNotVerified,
    load_schemes,
    readiness_checklist,
    render_checklist,
)
from core.state import Turn, handle_turn, produce_scheme_readiness_turn

agent = make_agent(
    name="recoverpay-orchestrator",
    seed_env="ORCHESTRATOR_SEED",
    port=8000,
    description=(
        "RecoverPay prepares overdue-invoice case packages for Indian MSME suppliers. "
        "Drafts for review only. Not legal advice. Never auto-sends messages."
    ),
)


def _session(ctx: Context, sender: str):
    store = ctx.storage.get("sessions") or {}
    return session_from_dict(store.get(sender)), store


def _save(ctx: Context, store: dict, sender: str, session) -> None:
    store[sender] = session_to_dict(session)
    ctx.storage.set("sessions", store)


async def _maybe_dispatch(ctx: Context, sender: str, session) -> None:
    if session.case is None or session.reconcile is None:
        return
    payload = json.dumps(
        {
            "type": "case_package",
            "from": "recoverpay-orchestrator",
            "case": to_dict(session.case),
            "reconcile": to_dict(session.reconcile),
            "estimate": to_dict(session.estimate) if session.estimate else None,
        }
    )
    rec_addr = os.getenv("RECONCILER_ADDRESS") if session.reconcile.mode == "full" else os.getenv(
        "RECONCILER_LITE_ADDRESS"
    )
    draft_addr = os.getenv("DRAFTER_ADDRESS")
    if rec_addr:
        await ctx.send(rec_addr, text_msg(payload))
        ctx.logger.info("Dispatched package to reconciler %s", rec_addr)
    if draft_addr:
        await ctx.send(draft_addr, text_msg(payload))
        ctx.logger.info("Dispatched package to drafter %s", draft_addr)
    _ = sender


async def on_text(ctx: Context, sender: str, text: str) -> Turn:
    specialist_addrs = {
        os.getenv("RECONCILER_ADDRESS"),
        os.getenv("RECONCILER_LITE_ADDRESS"),
        os.getenv("DRAFTER_ADDRESS"),
    }
    if sender in specialist_addrs:
        ctx.logger.info("Specialist note from %s: %s", sender, text[:200])
        return Turn("Specialist update recorded. Drafts remain unsent.")

    session, store = _session(ctx, sender)
    session, turn = handle_turn(session, text)
    _save(ctx, store, sender, session)
    if session.stage == "review":
        await _maybe_dispatch(ctx, sender, session)
    return turn


attach_chat(agent, on_text)


@agent.on_event("startup")
async def startup(ctx: Context) -> None:
    ctx.logger.info("RecoverPay orchestrator address: %s", agent.address)
    ctx.logger.info("Drafts for review only. Not legal advice. No auto-send.")


if __name__ == "__main__":
    agent.run()
