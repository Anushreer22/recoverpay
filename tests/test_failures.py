from core.calc import assess_eligibility, reconcile_case
from core.llm import build_drafts, draft_violations, sanitize_draft_text
from core.models import Session
from core.state import handle_turn, load_case
from core.calc import estimate_interest


def test_medium_enterprise_blocked():
    result = assess_eligibility(True, "medium", "manufacturing")
    assert result.eligible is False
    session, _ = handle_turn(Session(), "hello")
    session, turn = handle_turn(
        session,
        '{"action":"eligibility","registered":"yes","enterprise_class":"medium","activity":"manufacturing"}',
    )
    assert session.stage == "blocked"
    assert session.estimate is None
    assert "medium" in turn.text.lower()


def test_unregistered_blocked():
    result = assess_eligibility(False, "small", "services")
    assert result.eligible is False
    session, _ = handle_turn(Session(), "hi")
    session, turn = handle_turn(
        session,
        '{"action":"eligibility","registered":"no","enterprise_class":"small","activity":"services"}',
    )
    assert session.stage == "blocked"
    assert "registration" in turn.text.lower()


def test_trading_blocked():
    result = assess_eligibility(True, "small", "trading", "46900")
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
    drafts = build_drafts(case, estimate_interest(case), rec)
    assert all(d.kind == "document_request" for d in drafts)
    assert all("not legal advice" in d.body.lower() for d in drafts)


def test_forbidden_legal_language_is_stripped():
    dirty = "Pay now or we will sue and take legal action. You are liable."
    assert draft_violations(dirty)
    clean = sanitize_draft_text(dirty)
    assert "we will sue" not in clean.lower()
    assert "legal action" not in clean.lower()
    assert "not legal advice" in clean.lower()


def test_happy_path_drafts_are_factual():
    session, _ = handle_turn(Session(), "hi")
    session, _ = handle_turn(
        session,
        '{"action":"eligibility","registered":"yes","enterprise_class":"small","activity":"manufacturing"}',
    )
    session, _ = handle_turn(session, "case1_clean")
    assert session.drafts
    for draft in session.drafts:
        assert not draft_violations(draft.body)
        assert "for review only" in draft.body.lower() or draft.for_review_only
        assert "not legal advice" in draft.body.lower()
