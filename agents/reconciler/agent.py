from __future__ import annotations

import json

from uagents import Context

from core.acp import attach_chat, text_msg
from core.bootstrap import make_agent
from core.calc import reconcile_case
from core.models import case_from_dict, to_dict

agent = make_agent(
    name="recoverpay-reconciler",
    seed_env="RECONCILER_SEED",
    port=8001,
    description="Full PO/invoice/GRN reconciliation for RecoverPay. Advisory only.",
)


async def on_text(ctx: Context, sender: str, text: str):
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text_msg(
            "RecoverPay reconciler. Send JSON {\"type\":\"reconcile_request\",\"case\":{...}}. Advisory only."
        )
    if payload.get("type") not in {"reconcile_request", "case_package"} or "case" not in payload:
        return text_msg("Expected a case object. No portal actions are taken.")
    case = case_from_dict(payload["case"])
    result = reconcile_case(case, mode="full")
    ctx.logger.info("Reconciled %s matched=%s", case.case_id, result.matched)
    return text_msg(
        json.dumps({"type": "reconcile_result", "mode": "full", "result": to_dict(result)})
    )


attach_chat(agent, on_text)


@agent.on_event("startup")
async def startup(ctx: Context) -> None:
    ctx.logger.info("Reconciler address: %s", agent.address)


if __name__ == "__main__":
    agent.run()
