from core.models import Session
from core.state import handle_turn


def test_eligibility_is_asked_first():
    session, turn = handle_turn(Session(), "hello")
    assert session.stage == "eligibility"
    assert turn.card_kind == "form"
    assert "registration" in turn.text.lower() or "eligibility" in turn.text.lower()


def test_cannot_load_case_before_eligibility():
    session, turn = handle_turn(Session(), "hello")
    session, turn = handle_turn(session, "case1")
    assert session.stage in {"eligibility", "blocked"}
    assert session.case is None
    assert "eligib" in turn.text.lower() or turn.card_kind == "form"


def test_registered_micro_then_case1():
    session, _ = handle_turn(Session(), "hi")
    session, turn = handle_turn(
        session,
        '{"action":"eligibility","registered":"yes","enterprise_class":"small","activity":"manufacturing"}',
    )
    assert session.eligibility and session.eligibility.eligible
    assert session.stage == "intake"
    assert turn.card_kind == "carousel"
    session, turn = handle_turn(session, "case1")
    assert session.case is not None
    assert session.stage == "review"
    assert session.estimate is not None
    assert "estimate, verify" in turn.text
    assert session.drafts
    assert all(d.for_review_only for d in session.drafts)


def test_keep_package_does_not_send():
    session, _ = handle_turn(Session(), "hi")
    session, _ = handle_turn(
        session,
        '{"action":"eligibility","registered":"yes","enterprise_class":"micro","activity":"services"}',
    )
    session, _ = handle_turn(session, '{"action":"load_case","case_id":"case1_clean"}')
    session, turn = handle_turn(session, '{"action":"keep_package"}')
    assert session.stage == "done"
    assert "not" in turn.text.lower() and "sent" in turn.text.lower()
