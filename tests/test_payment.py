from uagents_core.contrib.protocols.payment import (
    CommitPayment,
    CompletePayment,
    Funds,
    RejectPayment,
    RequestPayment,
)

from core.models import CasePackage, Party, Session
from core.payment import create_payment_request, process_payment_commit
from core.state import handle_turn


def _sample_case() -> CasePackage:
    return CasePackage(
        case_id="case_pay_test",
        invoice_no="INV-PAY-001",
        invoice_date="2024-01-10",
        invoice_amount=150000.0,
        supplier=Party(name="Test Supplier Ltd", udyam="UDYAM-XX-001"),
        buyer=Party(name="Test Buyer Corp"),
        currency="INR",
        agreed_credit_days=30,
        payments_received=0.0,
    )


def test_create_payment_request():
    req = create_payment_request(
        invoice_no="INV-100",
        amount=150000.0,
        recipient_address="agent1qg8q2akju5ejwsyzkjyjssh7y4q4metk8u0umkc3ggqtq0xlf69ukt9tl84",
        currency="FET",
    )
    assert isinstance(req, RequestPayment)
    assert req.reference == "INV-100"
    assert len(req.accepted_funds) == 1
    assert req.accepted_funds[0].amount == "150000.00"
    assert req.accepted_funds[0].currency == "FET"
    assert req.metadata["claim_type"] == "msme_overdue_settlement"


def test_process_payment_commit_valid():
    session = Session()
    session.case = _sample_case()
    commit = CommitPayment(
        funds=Funds(amount="150000.00", currency="INR", payment_method="fet_direct"),
        recipient="agent1qg8q2akju5ejwsyzkjyjssh7y4q4metk8u0umkc3ggqtq0xlf69ukt9tl84",
        transaction_id="tx_123456789abcdef",
        reference="INV-PAY-001",
    )
    reply, msg = process_payment_commit(
        commit,
        session=session,
        recipient_agent="agent1qg8q2akju5ejwsyzkjyjssh7y4q4metk8u0umkc3ggqtq0xlf69ukt9tl84",
    )
    assert isinstance(reply, CompletePayment)
    assert reply.transaction_id == "tx_123456789abcdef"
    assert session.case.payments_received == 150000.0
    assert any(ev.get("step") == "payment_settlement" for ev in session.audit_events)


def test_process_payment_commit_rejects_missing_tx():
    session = Session()
    session.case = _sample_case()
    commit = CommitPayment(
        funds=Funds(amount="150000.00", currency="INR", payment_method="fet_direct"),
        recipient="agent1qg8q2akju5ejwsyzkjyjssh7y4q4metk8u0umkc3ggqtq0xlf69ukt9tl84",
        transaction_id="",
        reference="INV-PAY-001",
    )
    reply, msg = process_payment_commit(
        commit,
        session=session,
        recipient_agent="agent1qg8q2akju5ejwsyzkjyjssh7y4q4metk8u0umkc3ggqtq0xlf69ukt9tl84",
    )
    assert isinstance(reply, RejectPayment)


def test_payment_chat_flow_and_settlement(monkeypatch):
    from tests.test_state_machine import TEST_RULES

    session, _ = handle_turn(Session(rules=TEST_RULES), "hi")
    session, _ = handle_turn(
        session,
        '{"action":"eligibility","registered":"yes","enterprise_class":"micro","activity":"manufacturing"}',
    )
    session, _ = handle_turn(session, "case1")
    assert session.stage == "review"

    # User asks for settlement request
    session, turn = handle_turn(session, "request_payment")
    assert turn.card_kind == "review"
    assert "Payment Settlement Request" in turn.card_payload["title"]
    assert "AgentPaymentProtocol" in turn.text

    # User triggers simulated settlement
    session, turn = handle_turn(session, "simulate_settlement")
    assert session.stage == "done"
    assert "Payment Settlement Completed" in turn.text
    assert any(ev.get("step") == "payment_settlement" for ev in session.audit_events)
