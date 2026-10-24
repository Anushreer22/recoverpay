from core.guardrails import ESTIMATE_LABEL
from core.models import Session
from core.state import handle_turn

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


def test_eligibility_is_asked_first():
    session, turn = handle_turn(Session(rules=TEST_RULES), "hello")
    assert session.stage == "eligibility"
    assert turn.card_kind == "form"
    assert "registration" in turn.text.lower() or "eligibility" in turn.text.lower()


def test_cannot_load_case_before_eligibility():
    session, turn = handle_turn(Session(rules=TEST_RULES), "hello")
    session, turn = handle_turn(session, "case1")
    assert session.stage in {"eligibility", "blocked"}
    assert session.case is None
    assert "eligib" in turn.text.lower() or turn.card_kind == "form"


def test_registered_micro_then_case1():
    session, _ = handle_turn(Session(rules=TEST_RULES), "hi")
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
    assert ESTIMATE_LABEL in turn.text
    assert "estimate, verify before use" in turn.text.lower()
    assert session.drafts
    assert all(d.for_review_only for d in session.drafts)


def test_keep_package_does_not_send():
    session, _ = handle_turn(Session(rules=TEST_RULES), "hi")
    session, _ = handle_turn(
        session,
        '{"action":"eligibility","registered":"yes","enterprise_class":"micro","activity":"services"}',
    )
    session, _ = handle_turn(session, '{"action":"load_case","case_id":"case1_clean"}')
    session, turn = handle_turn(session, '{"action":"keep_package"}')
    assert session.stage == "done"
    assert "not" in turn.text.lower() and "sent" in turn.text.lower()


def test_agent_mention_stripped_and_reconcile_case_guidance():
    # Test agent mention prefix stripping
    session, turn = handle_turn(
        Session(rules=TEST_RULES),
        "@agent1qg8q2akju5ejwsyzkjyjssh7y4q4metk8u0umkc3ggqtq0xlf69ukt9tl84 reconcile_case",
    )
    # When before eligibility
    assert "eligib" in turn.text.lower() or turn.card_kind == "form"

    # Now confirm eligibility
    session, turn = handle_turn(
        session,
        "@agent1qg8q2akju5ejwsyzkjyjssh7y4q4metk8u0umkc3ggqtq0xlf69ukt9tl84 yes, registered micro",
    )
    assert session.stage == "intake"

    # Now sending reconcile_case when no case is loaded gives clear guidance
    session, turn = handle_turn(session, "reconcile_case")
    assert "load case1" in turn.text
    assert "new case" in turn.text

    # Loading a case with mention prefix
    session, turn = handle_turn(
        session,
        "@agent1qg8q2akju5ejwsyzkjyjssh7y4q4metk8u0umkc3ggqtq0xlf69ukt9tl84 load case1",
    )
    assert session.case is not None
    assert session.stage == "review"

    # Calling reconcile_case when case is loaded runs reconciliation and pipeline
    session, turn = handle_turn(session, "reconcile_case")
    assert session.case is not None
    assert session.stage == "review"
    assert "working file ready" in turn.text.lower()

