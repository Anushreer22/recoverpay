from __future__ import annotations

import json
from datetime import date
import pytest

from core.calc import estimate_interest
from core.models import CasePackage, Party, Session
from core.recovery import InProcessReconciler
from core.state import handle_turn
from core.validation import (
    check_overdue_status,
    parse_user_amount,
    parse_user_date,
    validate_and_normalize_case_data,
)

# TEST ONLY rules - Fictional statutory values for testing
FICTIONAL_RULES = {
    "_note": "TEST ONLY, not real legal values",
    "max_credit_days": {"value": 45, "source": "test-statute-sec-99", "verified": True},
    "default_credit_days": {"value": 15, "source": "test-statute-sec-99", "verified": True},
    "interest_multiplier": {"value": 3.0, "source": "test-statute-sec-99", "verified": True},
    "compounding_basis": {"value": "monthly", "source": "test-statute-sec-99", "verified": True},
    "day_count_month": {"value": 30, "source": "test-statute-sec-99", "verified": True},
    "rbi_bank_rate": {"value": 0.06, "source": "test-rbi-notice-00", "verified": True},
    "rbi_bank_rate_as_of": {"value": "2026-01-01", "source": "test-rbi-notice-00", "verified": True},
    "eligible_classes": {"value": ["micro", "small"], "source": "test-statute-sec-99", "verified": True},
    "ineligible_activities": {"value": ["trading"], "source": "test-statute-sec-99", "verified": True},
    "ineligible_nic_prefixes": {"value": ["45", "46", "47"], "source": "test-statute-sec-99", "verified": True},
    "registration_required": {"value": True, "source": "test-statute-sec-99", "verified": True},
    "disclaimer": {"value": "Draft for review only.", "source": "test-policy", "verified": True},
    "forbidden_draft_terms": {"value": ["legal action", "we will sue"], "source": "test-policy", "verified": True},
}


def _setup_confirmed_session() -> Session:
    """Helper to start session and confirm micro-manufacturing eligibility."""
    session = Session(rules=FICTIONAL_RULES)
    session, _ = handle_turn(session, "hi")
    session, turn = handle_turn(
        session,
        '{"action":"eligibility","registered":"yes","enterprise_class":"micro","activity":"manufacturing"}',
    )
    assert session.stage == "intake"
    return session


def test_good_extraction_and_confirmation(monkeypatch):
    """Verify good LLM extraction shows summary, waits for confirmation, records audit event, and runs pipeline."""
    session = _setup_confirmed_session()

    fake_extracted = {
        "supplier_name": "Fictional Precision Tools",
        "buyer_name": "Fictional Auto Assemblers",
        "invoice_no": "INV-FIC-2024-001",
        "invoice_date": "10-01-2024",
        "amount": "₹1,50,000",
        "agreed_terms_days": 30,
        "po_no": "PO-FIC-900",
        "po_amount": "1,50,000",
        "delivery_date": "15-01-2024",
        "signed_delivery_proof": True,
        "payments_received": 0,
        "notes": "Delivered CNC parts in full.",
        "multiple_invoices": False,
    }

    def fake_asi1(user_prompt: str, system_prompt: str) -> str:
        return json.dumps(fake_extracted)

    monkeypatch.setattr("core.llm.asi1_complete", fake_asi1)
    monkeypatch.setenv("ASI1_API_KEY", "fake_key")

    # User enters plain language description in intake
    user_prompt = "We delivered CNC parts under invoice INV-FIC-2024-001 dated 10-01-2024 for Rs 150000 to Fictional Auto Assemblers."
    session, turn = handle_turn(session, user_prompt, reconciler=InProcessReconciler())

    # Must be in case_confirm stage BEFORE running any calculations
    assert session.stage == "case_confirm"
    assert session.pending_case_data is not None
    assert "Case Summary:" in turn.text
    assert "Fictional Precision Tools" in turn.text
    assert "Fictional Auto Assemblers" in turn.text
    assert "INV-FIC-2024-001" in turn.text
    assert "₹150,000.00" in turn.text
    assert "confirm" in turn.text.lower()

    # Calculations have NOT run yet
    assert session.estimate is None
    assert session.reconcile is None
    assert len(session.drafts) == 0

    # User confirms the case
    session, turn = handle_turn(session, "confirm", reconciler=InProcessReconciler())

    # Calculations and pipeline run ONLY after confirmation
    assert session.stage == "review"
    assert session.case is not None
    assert session.case.invoice_no == "INV-FIC-2024-001"
    assert session.estimate is not None
    assert session.reconcile is not None
    assert len(session.drafts) > 0

    # Confirmation recorded in audit trail
    confirm_events = [e for e in session.audit_events if e["step"] == "case_confirmation"]
    assert len(confirm_events) == 1
    assert confirm_events[0]["actor"] == "user"
    assert confirm_events[0]["approval_status"] == "approved"
    assert confirm_events[0]["inputs"]["invoice_no"] == "INV-FIC-2024-001"


def test_missing_field_then_asked_one_by_one(monkeypatch):
    """Verify missing required fields are asked one at a time in plain language without guessing."""
    session = _setup_confirmed_session()

    # Extraction missing invoice_date and amount
    fake_extracted = {
        "supplier_name": "Fictional Parts Co",
        "buyer_name": "Fictional Motors Ltd",
        "invoice_no": "INV-FIC-909",
        "invoice_date": None,
        "amount": None,
        "agreed_terms_days": 30,
        "po_no": "PO-909",
        "po_amount": None,
        "delivery_date": None,
        "signed_delivery_proof": None,
        "payments_received": 0,
        "notes": "",
        "multiple_invoices": False,
    }

    monkeypatch.setattr("core.llm.asi1_complete", lambda *args, **kwargs: json.dumps(fake_extracted))
    monkeypatch.setenv("ASI1_API_KEY", "fake_key")

    session, turn = handle_turn(session, "Invoice INV-FIC-909 for Fictional Motors Ltd")

    # Stage transitions to case_intake, asks for first missing field (invoice_date)
    assert session.stage == "case_intake"
    assert session.missing_fields == ["invoice_date", "amount"]
    assert "invoice date" in turn.text.lower()

    # User provides invoice date in "5 Sept 2026" format
    session, turn = handle_turn(session, "5 Sept 2026")
    assert session.stage == "case_intake"
    assert session.missing_fields == ["amount"]
    assert session.pending_case_data["invoice_date"] == "2026-09-05"
    assert "invoice amount" in turn.text.lower()

    # User provides invoice amount with currency symbols and commas
    session, turn = handle_turn(session, "₹2,50,000")
    assert session.stage == "case_confirm"
    assert session.missing_fields == []
    assert session.pending_case_data["amount"] == 250000.0
    assert "Case Summary:" in turn.text
    assert "₹250,000.00" in turn.text


def test_invalid_json_then_fallback(monkeypatch):
    """Verify invalid JSON from ASI1 reports issue and falls back to asking fields one by one."""
    session = _setup_confirmed_session()

    # LLM returns malformed, non-JSON text
    monkeypatch.setattr(
        "core.llm.asi1_complete",
        lambda *args, **kwargs: "Here is the invoice info: Supplier: Fictional A, Buyer: Fictional B.",
    )
    monkeypatch.setenv("ASI1_API_KEY", "fake_key")

    session, turn = handle_turn(session, "We supplied goods to Fictional B")

    assert session.stage == "case_intake"
    assert "invalid json" in turn.text.lower() or "unavailable" in turn.text.lower()
    assert "falling back" in turn.text.lower()
    assert "supplier (your business) name" in turn.text.lower()
    assert session.missing_fields == ["supplier_name", "buyer_name", "invoice_no", "invoice_date", "amount"]


def test_asi1_unavailable_then_fallback(monkeypatch):
    """Verify when ASI1 is unavailable or missing key, system reports it and falls back to step-by-step entry."""
    session = _setup_confirmed_session()
    monkeypatch.delenv("ASI1_API_KEY", raising=False)
    monkeypatch.delenv("ASI_ONE_API_KEY", raising=False)

    session, turn = handle_turn(session, "We supplied goods to Fictional B under invoice 101")
    assert session.stage == "case_intake"
    assert "unavailable" in turn.text.lower() or "not configured" in turn.text.lower()
    assert "falling back" in turn.text.lower()
    assert "supplier (your business) name" in turn.text.lower()
    assert session.missing_fields == ["supplier_name", "buyer_name", "invoice_no", "invoice_date", "amount"]


def test_bad_date_rejected(monkeypatch):
    """Verify bad date formats and delivery dates before invoice date are rejected with plain messages."""
    session = _setup_confirmed_session()

    # 1. Invalid date string in extraction
    fake_bad_date = {
        "supplier_name": "Fictional Supplier",
        "buyer_name": "Fictional Buyer",
        "invoice_no": "INV-FIC-01",
        "invoice_date": "not-a-valid-date-32-13-2024",
        "amount": 50000.0,
        "multiple_invoices": False,
    }
    monkeypatch.setattr("core.llm.asi1_complete", lambda u, s: json.dumps(fake_bad_date))
    monkeypatch.setenv("ASI1_API_KEY", "fake_key")

    session, turn = handle_turn(session, "Case description with invalid date")
    assert "invalid date format" in turn.text.lower()
    assert session.stage == "intake"  # not progressed to confirm

    # 2. Delivery date before invoice date rejected
    fake_reversed_dates = {
        "supplier_name": "Fictional Supplier",
        "buyer_name": "Fictional Buyer",
        "invoice_no": "INV-FIC-02",
        "invoice_date": "2024-05-15",
        "delivery_date": "2024-05-01",
        "amount": 50000.0,
        "multiple_invoices": False,
    }
    monkeypatch.setattr("core.llm.asi1_complete", lambda *args, **kwargs: json.dumps(fake_reversed_dates))
    session, turn = handle_turn(session, "Case description with delivery before invoice")
    assert "cannot be before invoice date" in turn.text.lower()
    assert session.stage == "intake"


def test_user_corrects_field(monkeypatch):
    """Verify user can correct a field before confirming calculations."""
    session = _setup_confirmed_session()

    fake_extracted = {
        "supplier_name": "Fictional Alpha",
        "buyer_name": "Fictional Beta",
        "invoice_no": "INV-FIC-888",
        "invoice_date": "2024-02-01",
        "amount": 50000.0,
        "agreed_terms_days": 30,
        "multiple_invoices": False,
    }
    monkeypatch.setattr("core.llm.asi1_complete", lambda *args, **kwargs: json.dumps(fake_extracted))
    monkeypatch.setenv("ASI1_API_KEY", "fake_key")

    session, turn = handle_turn(session, "Invoice INV-FIC-888 description")
    assert session.stage == "case_confirm"
    assert "₹50,000.00" in turn.text

    # User corrects amount to 75000
    session, turn = handle_turn(session, "correct amount 75000")
    assert session.stage == "case_confirm"
    assert session.pending_case_data["amount"] == 75000.0
    assert "₹75,000.00" in turn.text
    assert "Field 'amount' updated" in turn.text

    # User confirms with corrected amount
    session, turn = handle_turn(session, "confirm", reconciler=InProcessReconciler())
    assert session.stage == "review"
    assert session.case.invoice_amount == 75000.0


def test_user_cancels(monkeypatch):
    """Verify user can cancel case intake without running calculations."""
    session = _setup_confirmed_session()

    fake_extracted = {
        "supplier_name": "Fictional Alpha",
        "buyer_name": "Fictional Beta",
        "invoice_no": "INV-FIC-777",
        "invoice_date": "2024-02-01",
        "amount": 50000.0,
        "multiple_invoices": False,
    }
    monkeypatch.setattr("core.llm.asi1_complete", lambda *args, **kwargs: json.dumps(fake_extracted))
    monkeypatch.setenv("ASI1_API_KEY", "fake_key")

    session, turn = handle_turn(session, "Invoice INV-FIC-777 description")
    assert session.stage == "case_confirm"

    # User cancels
    session, turn = handle_turn(session, "cancel")
    assert session.stage == "intake"
    assert session.pending_case_data is None
    assert "cancelled" in turn.text.lower()
    assert session.estimate is None


def test_not_overdue_notice(monkeypatch):
    """Verify invoice that is not overdue shows clear notice under MSMED Section 15."""
    session = _setup_confirmed_session()

    # Invoice dated today with 30 days credit is not overdue
    today_str = date.today().isoformat()
    fake_extracted = {
        "supplier_name": "Fictional Alpha",
        "buyer_name": "Fictional Beta",
        "invoice_no": "INV-RECENT-01",
        "invoice_date": today_str,
        "amount": 100000.0,
        "agreed_terms_days": 30,
        "multiple_invoices": False,
    }
    monkeypatch.setattr("core.llm.asi1_complete", lambda *args, **kwargs: json.dumps(fake_extracted))
    monkeypatch.setenv("ASI1_API_KEY", "fake_key")

    session, turn = handle_turn(session, "New invoice dated today")
    assert session.stage == "case_confirm"
    assert "not overdue yet" in turn.text.lower()
    assert "section 15 of the msmed act" in turn.text.lower()


def test_partial_payment_calculation_and_notice(monkeypatch):
    """Verify partial payments are deducted from principal for statutory interest estimation."""
    session = _setup_confirmed_session()

    fake_extracted = {
        "supplier_name": "Fictional Supplier Ltd",
        "buyer_name": "Fictional Buyer Ltd",
        "invoice_no": "INV-PARTIAL-01",
        "invoice_date": "2024-01-01",
        "amount": "₹1,00,000",
        "agreed_terms_days": 15,
        "payments_received": "₹40,000",
        "delivery_date": "2024-01-02",
        "signed_delivery_proof": True,
        "multiple_invoices": False,
    }
    monkeypatch.setattr("core.llm.asi1_complete", lambda *args, **kwargs: json.dumps(fake_extracted))
    monkeypatch.setenv("ASI1_API_KEY", "fake_key")

    session, turn = handle_turn(session, "Invoice with partial payment")
    assert session.stage == "case_confirm"
    assert "partial payments of ₹40,000.00 recorded" in turn.text.lower()
    assert "remaining principal only (₹60,000.00)" in turn.text.lower()

    # User confirms
    session, turn = handle_turn(session, "confirm", reconciler=InProcessReconciler())
    assert session.stage == "review"
    assert session.case.invoice_amount == 100000.0
    assert session.case.payments_received == 40000.0
    # Interest calculation principal must be exactly 60,000.0
    assert session.estimate.principal == 60000.0
    assert any("remaining principal only" in c.lower() for c in session.estimate.caveats)


def test_more_than_one_invoice_rejected(monkeypatch):
    """Verify description containing more than one invoice is rejected with plain guidance."""
    session = _setup_confirmed_session()

    fake_extracted = {
        "multiple_invoices": True,
        "notes": "User mentioned invoices INV-01 and INV-02",
    }
    monkeypatch.setattr("core.llm.asi1_complete", lambda *args, **kwargs: json.dumps(fake_extracted))
    monkeypatch.setenv("ASI1_API_KEY", "fake_key")

    session, turn = handle_turn(session, "We have 2 unpaid invoices INV-01 and INV-02 from Fictional Buyer")
    assert session.stage == "intake"
    assert "multiple invoices detected" in turn.text.lower()
    assert "one overdue invoice at a time" in turn.text.lower()


def test_medium_enterprise_or_unregistered_blocked():
    """Verify unregistered suppliers and medium enterprises remain blocked before calculations."""
    # 1. Unregistered supplier
    session = Session(rules=FICTIONAL_RULES)
    session, _ = handle_turn(session, "hi")
    session, turn = handle_turn(
        session,
        '{"action":"eligibility","registered":"no","enterprise_class":"micro","activity":"manufacturing"}',
    )
    assert session.stage == "blocked"
    assert "stopped before calculations" in turn.text.lower()
    assert "supplier registration (udyam) is not confirmed" in turn.text.lower()

    # 2. Medium enterprise
    session2 = Session(rules=FICTIONAL_RULES)
    session2, _ = handle_turn(session2, "hi")
    session2, turn2 = handle_turn(
        session2,
        '{"action":"eligibility","registered":"yes","enterprise_class":"medium","activity":"manufacturing"}',
    )
    assert session2.stage == "blocked"
    assert "stopped before calculations" in turn2.text.lower()
    assert "medium" in turn2.text.lower()


def test_hand_calculated_monthly_rest_interest():
    """Verify hand-calculated statutory monthly-rest compound interest example.

    Hand calculation:
    - Principal: ₹1,00,000.00 (Fictional Alpha Supplies)
    - RBI Bank Rate: 6.0% (0.06)
    - Interest Multiplier: 3.0x -> Annual Rate = 18.0% (0.18)
    - Compounding: Monthly rests (12 rests/year -> 1.5% = 0.015 per month)
    - Day count convention: 30 days per month
    - Overdue duration: Exactly 60 days (2 full compounding rests, 0 remainder days)

    Accrual:
    Month 1: ₹1,00,000.00 * (1 + 0.015) = ₹1,01,500.00 (Interest = ₹1,500.00)
    Month 2: ₹1,01,500.00 * (1 + 0.015) = ₹1,03,022.50 (Interest = ₹1,522.50)
    Total Interest = ₹1,500.00 + ₹1,522.50 = ₹3,022.50
    Total Claim = Principal (₹1,00,000.00) + Interest (₹3,022.50) = ₹1,03,022.50
    """
    case = CasePackage(
        case_id="case_hand_calc_fictional",
        supplier=Party(name="Fictional Alpha Supplies"),
        buyer=Party(name="Fictional Beta Components"),
        invoice_no="INV-HAND-001",
        invoice_date="2026-01-01",
        invoice_amount=100000.0,
        accepted_date="2026-01-01",
        agreed_credit_days=0,  # Due immediately on 2026-01-01
        payments_received=0.0,
    )

    # 60 days after 2026-01-01 is 2026-03-02 (January 31 days + February 28 days + 1 day)
    as_of = date(2026, 3, 2)
    estimate = estimate_interest(case, as_of=as_of, rules=FICTIONAL_RULES)

    assert estimate.principal == 100000.0
    assert estimate.annual_rate == 0.18
    assert estimate.overdue_days == 60
    # Exact hand-calculated values:
    assert estimate.interest == 3022.50
    assert estimate.total == 103022.50
