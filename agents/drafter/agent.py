from __future__ import annotations

import json

from uagents import Context

from core.acp import attach_chat, text_msg
from core.bootstrap import make_agent
from core.calc import estimate_interest, pick_reconcile_mode, reconcile_case
from core.guardrails import DRAFT_BANNER
from core.llm import build_drafts_with_status, draft_violations
from core.messages import DraftRequest, DraftResponse
from core.models import (
    Finding,
    InterestEstimate,
    ReconcileResult,
    case_from_dict,
    to_dict,
)

agent = make_agent(
    name="recoverpay-drafter",
    seed_env="DRAFTER_SEED",
    port=8003,
    description=(
        "Drafts factual payment reminders, document check notices, and case summaries for Indian MSME suppliers. "
        "Drafts for review only. Never sends messages. Not legal advice."
    ),
)


@agent.on_message(model=DraftRequest)
async def handle_draft_request(ctx: Context, sender: str, msg: DraftRequest) -> None:
    case = case_from_dict(msg.case)
    rec_data = msg.reconcile or {}
    rec = ReconcileResult(
        mode=rec_data.get("mode", "full"),
        matched=bool(rec_data.get("matched", False)),
        evidence_complete=bool(rec_data.get("evidence_complete", False)),
        can_draft_payment_reminder=bool(rec_data.get("can_draft_payment_reminder", False)),
        findings=[Finding(**f) for f in rec_data.get("findings", [])],
        notes=rec_data.get("notes", ""),
    )
    est_data = msg.estimate or {}
    est = None
    if est_data:
        try:
            est = InterestEstimate(**est_data)
        except Exception:
            est = estimate_interest(case)
    if est is None:
        est = estimate_interest(case)

    drafts, used_asi1 = build_drafts_with_status(case, est, rec, use_llm=True)
    for d in drafts:
        if draft_violations(d.body):
            d.body = f"{DRAFT_BANNER}\n\nDraft blocked by language guardrail. Factual template required."

    ctx.logger.info(
        "Drafter prepared %s draft(s) for %s (used_asi1=%s)",
        len(drafts),
        case.invoice_no,
        used_asi1,
    )
    await ctx.send(
        sender,
        DraftResponse(
            request_id=msg.request_id,
            case_id=case.case_id,
            drafts=to_dict(drafts),
            used_fallback_llm=not used_asi1,
        ),
    )


async def on_text(ctx: Context, sender: str, text: str):
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text_msg(
            "RecoverPay Drafter agent. Prepares factual reminders and document check notices. "
            "Send JSON with a case object. Drafts remain unsent. Not legal advice."
        )

    if "case" not in payload:
        return text_msg("Expected a case object in JSON. Nothing will be sent.")

    case = case_from_dict(payload["case"])
    rec_data = payload.get("reconcile")
    if rec_data:
        rec = ReconcileResult(
            mode=rec_data.get("mode", "full"),
            matched=bool(rec_data.get("matched", False)),
            evidence_complete=bool(rec_data.get("evidence_complete", False)),
            can_draft_payment_reminder=bool(rec_data.get("can_draft_payment_reminder", False)),
            findings=[Finding(**f) for f in rec_data.get("findings", [])],
            notes=rec_data.get("notes", ""),
        )
    else:
        rec = reconcile_case(case, mode=pick_reconcile_mode(case))

    est = estimate_interest(case)
    drafts, used_asi1 = build_drafts_with_status(case, est, rec, use_llm=True)
    for d in drafts:
        if draft_violations(d.body):
            d.body = f"{DRAFT_BANNER}\n\nDraft blocked by language guardrail. Factual template required."

    ctx.logger.info("Chat drafted %s items (used_asi1=%s)", len(drafts), used_asi1)
    return text_msg(
        json.dumps(
            {
                "type": "draft_result",
                "unsent": True,
                "not_legal_advice": True,
                "used_fallback_llm": not used_asi1,
                "drafts": to_dict(drafts),
            }
        )
    )


attach_chat(agent, on_text)


@agent.on_event("startup")
async def startup(ctx: Context) -> None:
    ctx.logger.info("RecoverPay Drafter address: %s", agent.address)
    ctx.logger.info("Drafter ready. Reminder, notice, and summary drafts are unsent.")


if __name__ == "__main__":
    agent.run()
