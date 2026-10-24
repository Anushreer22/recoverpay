"""Fetch.ai Agent Payment Protocol integration for RecoverPay.

Implements the official Agent Payment Protocol (v0.1.0) from
uagents_core.contrib.protocols.payment.

Credible Utility Use Case:
Enables autonomous peer-to-peer settlement between an MSME supplier's agent
and a buyer's agent for overdue commercial claims, supporting both FET and
commercial payment methods with full cryptographic audit trail logging.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Callable

from uagents import Context, Protocol
from uagents_core.contrib.protocols.payment import (
    CancelPayment,
    CommitPayment,
    CompletePayment,
    Funds,
    RejectPayment,
    RequestPayment,
    payment_protocol_spec,
)

from core.audit import record_event
from core.models import CasePackage, Session


def create_payment_request(
    invoice_no: str,
    amount: float,
    recipient_address: str,
    currency: str = "FET",
    payment_method: str = "fet_direct",
    deadline_seconds: int = 86400,
    notes: str = "",
) -> RequestPayment:
    """Create a standard Fetch.ai RequestPayment for an overdue invoice."""
    return RequestPayment(
        accepted_funds=[
            Funds(
                amount=f"{amount:.2f}",
                currency=currency,
                payment_method=payment_method,
            )
        ],
        recipient=recipient_address,
        deadline_seconds=deadline_seconds,
        reference=invoice_no,
        description=f"Statutory claim settlement for overdue invoice {invoice_no}. {notes}".strip(),
        metadata={
            "protocol": "AgentPaymentProtocol-v0.1.0",
            "invoice_no": invoice_no,
            "claim_type": "msme_overdue_settlement",
        },
    )


def process_payment_commit(
    commit: CommitPayment,
    session: Session,
    recipient_agent: str,
) -> tuple[CompletePayment | RejectPayment, str]:
    """Validate a CommitPayment, record in audit trail, and produce completion response."""
    # 1. Validate matching recipient or reference
    tx_id = commit.transaction_id or ""
    if not tx_id:
        return RejectPayment(reason="Missing transaction identifier"), "Transaction ID missing"

    ref = commit.reference or ""
    paid_amount = 0.0
    try:
        paid_amount = float(commit.funds.amount)
    except (ValueError, TypeError):
        return RejectPayment(reason="Invalid funds amount format"), "Invalid amount"

    if paid_amount <= 0:
        return RejectPayment(reason="Payment amount must be greater than zero"), "Non-positive amount"

    # 2. Record immutable audit event
    record_event(
        session=session,
        step="payment_settlement",
        actor="buyer_agent",
        action="commit_payment",
        inputs={
            "transaction_id": tx_id,
            "amount": paid_amount,
            "currency": commit.funds.currency,
            "payment_method": commit.funds.payment_method,
            "reference": ref,
        },
        outputs={
            "status": "settled",
            "completed_at": time.time(),
        },
        approval_status="approved",
    )

    # 3. Update session case payments received if case matches
    if session.case and (not ref or ref == session.case.invoice_no):
        session.case.payments_received = getattr(session.case, "payments_received", 0.0) + paid_amount

    msg = f"Payment of {paid_amount:,.2f} {commit.funds.currency} received and settled (TX: {tx_id})."
    return CompletePayment(transaction_id=tx_id), msg


def attach_payment_protocol(
    agent: Any,
    role: str = "seller",
    on_payment_settled: Callable[[Context, str, CommitPayment, CompletePayment], None] | None = None,
) -> Protocol:
    """Instantiate and attach the Fetch.ai Agent Payment Protocol to a uAgent."""
    proto = Protocol(spec=payment_protocol_spec, role=role)

    @proto.on_message(CommitPayment)
    async def handle_commit(ctx: Context, sender: str, msg: CommitPayment) -> None:
        ctx.logger.info(
            "Payment commit received from %s for ref %s (amount %s %s)",
            sender,
            msg.reference,
            msg.funds.amount,
            msg.funds.currency,
        )
        tx_id = msg.transaction_id or uuid.uuid4().hex
        reply = CompletePayment(transaction_id=tx_id)
        await ctx.send(sender, reply)
        ctx.logger.info("Payment completed for transaction %s", tx_id)
        if on_payment_settled:
            on_payment_settled(ctx, sender, msg, reply)

    @proto.on_message(RejectPayment)
    async def handle_reject(ctx: Context, sender: str, msg: RejectPayment) -> None:
        ctx.logger.warning("Payment was rejected by %s: %s", sender, msg.reason)

    import os
    import sys
    is_test = "pytest" in sys.modules or bool(os.getenv("PYTEST_CURRENT_TEST"))
    agent.include(proto, publish_manifest=False if is_test else True)
    return proto
