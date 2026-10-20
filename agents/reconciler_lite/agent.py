from __future__ import annotations

import json

from uagents import Context

from core.acp import attach_chat, text_msg
from core.bootstrap import make_agent
from core.calc import reconcile_case
from core.models import case_from_dict, to_dict

agent = make_agent(
    name="recoverpay-reconciler-lite",
    seed_env="RECONCILER_LITE_SEED",
    port=8002,
    description="Lite reconciliation when RecoverPay evidence is incomplete. Advisory only.",
)


async def on_text(ctx: Context, sender: str, text: str):
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text_msg(
            "RecoverPay lite reconciler. Send JSON {\"type\":\"reconcile_request\",\"case\":{...}}."
        )
    if "case" not in payload:
        return text_msg("Expected a case object.")
    case = case_from_dict(payload["case"])
    result = reconcile_case(case, mode="lite")
    ctx.logger.info("Lite reconcile %s evidence_complete=%s", case.case_id, result.evidence_complete)
    return text_msg(
        json.dumps({"type": "reconcile_result", "mode": "lite", "result": to_dict(result)})
    )


attach_chat(agent, on_text)


@agent.on_event("startup")
async def startup(ctx: Context) -> None:
    ctx.logger.info("Reconciler-lite address: %s", agent.address)


if __name__ == "__main__":
    agent.run()
