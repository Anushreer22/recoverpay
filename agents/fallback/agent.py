from __future__ import annotations

import json

from uagents import Context

from core.acp import attach_chat, text_msg
from core.bootstrap import make_agent
from core.messages import ReconcileRequest, ReconcileResponse
from core.models import case_from_dict, to_dict
from core.recovery import run_fallback_reconciliation

agent = make_agent(
    name="recoverpay-fallback",
    seed_env="FALLBACK_SEED",
    port=8002,
    description=(
        "Rule-based fallback check (mode 'lite') with fewer checks when evidence is incomplete "
        "or verifier is unavailable. Advisory only. Not legal advice."
    ),
    fallback_seed_envs=["RECONCILER_LITE_SEED"],
)


@agent.on_message(model=ReconcileRequest)
async def handle_reconcile_request(ctx: Context, sender: str, msg: ReconcileRequest) -> None:
    case = case_from_dict(msg.case)
    result = run_fallback_reconciliation(case)
    ctx.logger.info("Fallback reconciled %s in mode lite (fewer checks)", case.case_id)
    await ctx.send(
        sender,
        ReconcileResponse(
            request_id=msg.request_id,
            case_id=case.case_id,
            mode="lite",
            result=to_dict(result),
            notes=result.notes,
        ),
    )


async def on_text(ctx: Context, sender: str, text: str):
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text_msg(
            "RecoverPay Fallback agent. Provides rule-based 'lite' reconciliation with fewer checks. "
            "Send JSON with a case object to run fallback reconciliation. Advisory only."
        )

    if "case" not in payload:
        return text_msg("Expected a case object in JSON.")

    case = case_from_dict(payload["case"])
    result = run_fallback_reconciliation(case)
    ctx.logger.info("Chat fallback reconciled %s", case.case_id)
    return text_msg(
        json.dumps(
            {
                "type": "reconcile_result",
                "mode": "lite",
                "result": to_dict(result),
                "notes": result.notes,
            }
        )
    )


attach_chat(agent, on_text)


@agent.on_event("startup")
async def startup(ctx: Context) -> None:
    ctx.logger.info("RecoverPay Fallback address: %s", agent.address)
    ctx.logger.info("Fallback lite reconciler ready. Fewer checks applied.")


if __name__ == "__main__":
    agent.run()

