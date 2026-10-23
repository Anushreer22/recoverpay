from __future__ import annotations

import json
import os

from uagents import Context

from core.acp import attach_chat, text_msg
from core.bootstrap import make_agent
from core.calc import reconcile_case
from core.messages import ReconcileRequest, ReconcileResponse
from core.models import case_from_dict, to_dict

agent = make_agent(
    name="recoverpay-verifier",
    seed_env="VERIFIER_SEED",
    port=8001,
    description=(
        "Full evidence check (PO, invoice, GRN) for Indian MSME overdue claims. "
        "Drafts for review only. Not legal advice. Never auto-sends messages."
    ),
    fallback_seed_envs=["RECONCILER_SEED"],
)


def _is_force_fail() -> bool:
    return os.getenv("FORCE_FAIL", "").strip().lower() in {"true", "1", "yes"}


@agent.on_message(model=ReconcileRequest)
async def handle_reconcile_request(ctx: Context, sender: str, msg: ReconcileRequest) -> None:
    if _is_force_fail():
        ctx.logger.warning("FORCE_FAIL=true enabled; Verifier will not reply.")
        return

    case = case_from_dict(msg.case)
    result = reconcile_case(case, mode=msg.mode or "full")
    ctx.logger.info("Verifier reconciled %s matched=%s", case.case_id, result.matched)
    await ctx.send(
        sender,
        ReconcileResponse(
            request_id=msg.request_id,
            case_id=case.case_id,
            mode="full",
            result=to_dict(result),
            notes=result.notes,
        ),
    )


async def on_text(ctx: Context, sender: str, text: str):
    if _is_force_fail():
        ctx.logger.warning("FORCE_FAIL=true enabled; Verifier chat will not reply.")
        return None

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text_msg(
            "RecoverPay Verifier agent. Performs full evidence cross-checks (PO, GRN, invoice). "
            "Send JSON with a case object to run verification. Advisory only."
        )

    if payload.get("type") not in {"reconcile_request", "case_package"} or "case" not in payload:
        return text_msg("Expected a case object in JSON. Advisory only.")

    case = case_from_dict(payload["case"])
    result = reconcile_case(case, mode="full")
    ctx.logger.info("Chat verified %s matched=%s", case.case_id, result.matched)
    return text_msg(
        json.dumps({"type": "reconcile_result", "mode": "full", "result": to_dict(result)})
    )


attach_chat(agent, on_text)


@agent.on_event("startup")
async def startup(ctx: Context) -> None:
    ctx.logger.info("RecoverPay Verifier address: %s", agent.address)
    ctx.logger.info("Full evidence check ready. Drafts for review only.")


if __name__ == "__main__":
    agent.run()

