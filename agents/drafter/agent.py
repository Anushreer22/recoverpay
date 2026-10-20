from __future__ import annotations

import json

from uagents import Context

from core.acp import attach_chat, text_msg
from core.bootstrap import make_agent
from core.calc import estimate_interest, pick_reconcile_mode, reconcile_case
from core.llm import build_drafts, draft_violations
from core.models import case_from_dict, to_dict

agent = make_agent(
    name="recoverpay-drafter",
    seed_env="DRAFTER_SEED",
    port=8003,
    description="Drafts factual overdue-invoice notes for review. Never sends. Not legal advice.",
)


async def on_text(ctx: Context, sender: str, text: str):
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text_msg(
            "RecoverPay drafter. Send JSON with a case. Drafts are for review only and are never sent."
        )
    if "case" not in payload:
        return text_msg("Expected a case object. Nothing will be sent.")
    case = case_from_dict(payload["case"])
    rec = payload.get("reconcile")
    if rec:
        from core.models import Finding, ReconcileResult

        result = ReconcileResult(
            **{**rec, "findings": [Finding(**f) for f in rec.get("findings", [])]}
        )
    else:
        result = reconcile_case(case, mode=pick_reconcile_mode(case))
    estimate = estimate_interest(case)
    drafts = build_drafts(case, estimate, result)
    for draft in drafts:
        if draft_violations(draft.body):
            return text_msg("Draft blocked: factual language only. Not legal advice.")
    ctx.logger.info("Prepared %s unsent draft(s) for %s", len(drafts), case.invoice_no)
    return text_msg(
        json.dumps(
            {
                "type": "draft_result",
                "unsent": True,
                "not_legal_advice": True,
                "drafts": to_dict(drafts),
            }
        )
    )


attach_chat(agent, on_text)


@agent.on_event("startup")
async def startup(ctx: Context) -> None:
    ctx.logger.info("Drafter address: %s", agent.address)


if __name__ == "__main__":
    agent.run()
