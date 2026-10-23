from datetime import date
import pytest

from core.calc import RulesNotVerified, assess_eligibility, estimate_interest, load_rules, reconcile_case
from core.guardrails import DRAFT_BANNER, ESTIMATE_LABEL
from core.llm import build_drafts
from core.state import load_case

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


def test_estimate_label_always_present():
    case = load_case("case1_clean")
    estimate = estimate_interest(case, as_of=date(2026, 10, 20), rules=TEST_RULES)
    assert estimate.label == ESTIMATE_LABEL
    assert estimate.label == "Estimate, verify before use"
    assert "Estimate, verify before use" in estimate.method


def test_not_overdue_is_zero():
    case = load_case("case1_clean")
    estimate = estimate_interest(case, as_of=date(2026, 6, 30), rules=TEST_RULES)
    assert estimate.overdue_days == 0
    assert estimate.interest == 0


def test_credit_days_capped_at_45():
    case = load_case("case1_clean")
    case.agreed_credit_days = 90
    estimate = estimate_interest(case, as_of=date(2026, 10, 20), rules=TEST_RULES)
    assert estimate.due_date == "2026-07-12"
    assert any("45" in c for c in estimate.caveats)


def test_compound_interest_is_positive_when_overdue():
    case = load_case("case1_clean")
    estimate = estimate_interest(case, as_of=date(2026, 10, 20), rules=TEST_RULES)
    assert estimate.overdue_days > 0
    assert estimate.interest > 0
    assert estimate.total == round(case.invoice_amount + estimate.interest, 2)


def test_eligibility_micro_manufacturing():
    result = assess_eligibility(True, "micro", "manufacturing", "25999", rules=TEST_RULES)
    assert result.eligible is True


def test_real_rules_calc_raises_rules_not_verified():
    case = load_case("case1_clean")
    with pytest.raises(RulesNotVerified) as exc_info:
        estimate_interest(case)
    assert exc_info.value.key in [
        "max_credit_days",
        "rbi_bank_rate",
        "interest_multiplier",
        "day_count_month",
        "compounding_basis",
    ]


def test_real_rules_eligibility_raises_rules_not_verified():
    with pytest.raises(RulesNotVerified) as exc_info:
        assess_eligibility(True, "micro", "manufacturing")
    assert exc_info.value.key in [
        "registration_required",
        "eligible_classes",
        "ineligible_activities",
        "ineligible_nic_prefixes",
    ]


def test_guardrails_estimate_and_draft_exact_banners():
    case = load_case("case1_clean")
    estimate = estimate_interest(case, as_of=date(2026, 10, 20), rules=TEST_RULES)
    assert estimate.label == "Estimate, verify before use"
    assert "Estimate, verify before use" in estimate.method

    rec = reconcile_case(case, mode="full")
    drafts = build_drafts(case, estimate, rec, rules=TEST_RULES)
    assert len(drafts) > 0
    for draft in drafts:
        assert DRAFT_BANNER in draft.body
        assert "DRAFT FOR REVIEW. Not legal advice." in draft.body
