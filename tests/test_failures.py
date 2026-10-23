from core.calc import assess_eligibility, estimate_interest, reconcile_case
from core.guardrails import DRAFT_BANNER
from core.llm import build_drafts, draft_violations, sanitize_draft_text
from core.models import Session
from core.state import handle_turn, load_case

# TEST ONLY, not legal values
TEST_RULES = {
    "_note": "TEST ONLY, not legal values",
    "max_credit_days": {"value": 45, "source": "fake-statute-sec-99", "verified": True},
    "default_credit_days": {"value": 15, "source": "fake-statute-sec-99", "verified": True},
    "interest_multiplier": {"value": 3.0, "source": "fake-statute-sec-99", "verified": True},
    "compounding_basis": {"value": "monthly", "source": "fake-statute-sec-99", "verified": True},
    "day_count_month": {"value": 30, "source": "fake-statute-sec-99", "verified": True},
    "rbi_bank_rate": {"value": 0.065, "source": "fake-rbi-notice-00", "verified": True},
    "rbi_bank_rate_as_of": {"value": "2025-06-06", "source": "fake-rbi-notice-00", "verified": True},
    "eligible_classes": {"value": ["micro", "small"], "source": "fake-statute-sec-99", "verified": True},
    "ineligible_activities": {"value": ["trading"], "source": "fake-statute-sec-99", "verified": True},
    "ineligible_nic_prefixes": {"value": ["45", "46", "47"], "source": "fake-statute-sec-99", "verified": True},
    "registration_required": {"value": True, "source": "fake-statute-sec-99", "verified": True},
    "disclaimer": {"value": "Test disclaimer", "source": "fake-statute-sec-99", "verified": True},
    "forbidden_draft_terms": {"value": ["legal action", "we will sue"], "source": "fake-statute-sec-99", "verified": True},
}


def test_medium_enterprise_blocked():
    result = assess_eligibility(True, "medium", "manufacturing", rules=TEST_RULES)
    assert result.eligible is False
    session, _ = handle_turn(Session(rules=TEST_RULES), "hello")
    session, turn = handle_turn(
        session,
        '{"action":"eligibility","registered":"yes","enterprise_class":"medium","activity":"manufacturing"}',
    )
    assert session.stage == "blocked"
    assert session.estimate is None
    assert "medium" in turn.text.lower()


def test_unregistered_blocked():
    result = assess_eligibility(False, "small", "services", rules=TEST_RULES)
    assert result.eligible is False
    session, _ = handle_turn(Session(rules=TEST_RULES), "hi")
    session, turn = handle_turn(
        session,
        '{"action":"eligibility","registered":"no","enterprise_class":"small","activity":"services"}',
    )
    assert session.stage == "blocked"
    assert "registration" in turn.text.lower()


def test_trading_blocked():
    result = assess_eligibility(True, "small", "trading", "46900", rules=TEST_RULES)
    assert result.eligible is False


def test_po_mismatch_flagged():
    case = load_case("case2_po_mismatch")
    rec = reconcile_case(case, mode="full")
    codes = {f.code for f in rec.findings}
    assert "po_qty_mismatch" in codes
    assert rec.matched is False


def test_no_delivery_proof_blocks_payment_reminder():
    case = load_case("case3_no_delivery_proof")
    rec = reconcile_case(case, mode="lite")
    assert rec.can_draft_payment_reminder is False
    drafts = build_drafts(case, estimate_interest(case, rules=TEST_RULES), rec, rules=TEST_RULES)
    assert all(d.kind == "document_request" for d in drafts)
    assert all("not legal advice" in d.body.lower() for d in drafts)
    assert all(DRAFT_BANNER in d.body for d in drafts)


def test_forbidden_legal_language_is_stripped():
    dirty = "Pay now or we will sue and take legal action. You are liable."
    assert draft_violations(dirty, rules=TEST_RULES)
    clean = sanitize_draft_text(dirty, rules=TEST_RULES)
    assert "we will sue" not in clean.lower()
    assert "legal action" not in clean.lower()
    assert "not legal advice" in clean.lower()
    assert DRAFT_BANNER in clean


def test_happy_path_drafts_are_factual():
    session, _ = handle_turn(Session(rules=TEST_RULES), "hi")
    session, _ = handle_turn(
        session,
        '{"action":"eligibility","registered":"yes","enterprise_class":"small","activity":"manufacturing"}',
    )
    session, _ = handle_turn(session, "case1_clean")
    assert session.drafts
    for draft in session.drafts:
        assert not draft_violations(draft.body, rules=TEST_RULES)
        assert "for review only" in draft.body.lower() or draft.for_review_only
        assert "not legal advice" in draft.body.lower()
        assert DRAFT_BANNER in draft.body
