from datetime import date

from core.calc import assess_eligibility, estimate_interest, load_rules
from core.models import ESTIMATE_LABEL
from core.state import load_case


def test_estimate_label_always_present():
    case = load_case("case1_clean")
    estimate = estimate_interest(case, as_of=date(2026, 10, 20))
    assert estimate.label == ESTIMATE_LABEL
    assert estimate.label == load_rules()["estimate_label"]
    assert "estimate, verify" in estimate.method


def test_not_overdue_is_zero():
    case = load_case("case1_clean")
    estimate = estimate_interest(case, as_of=date(2026, 6, 30))
    assert estimate.overdue_days == 0
    assert estimate.interest == 0


def test_credit_days_capped_at_45():
    case = load_case("case1_clean")
    case.agreed_credit_days = 90
    estimate = estimate_interest(case, as_of=date(2026, 10, 20))
    assert estimate.due_date == "2026-07-12"
    assert any("45" in c for c in estimate.caveats)


def test_compound_interest_is_positive_when_overdue():
    case = load_case("case1_clean")
    estimate = estimate_interest(case, as_of=date(2026, 10, 20))
    assert estimate.overdue_days > 0
    assert estimate.interest > 0
    assert estimate.total == round(case.invoice_amount + estimate.interest, 2)


def test_eligibility_micro_manufacturing():
    result = assess_eligibility(True, "micro", "manufacturing", "25999")
    assert result.eligible is True
