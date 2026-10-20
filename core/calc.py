from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from core.models import (
    ESTIMATE_LABEL,
    CasePackage,
    Eligibility,
    Finding,
    InterestEstimate,
    ReconcileResult,
)

RULES_PATH = Path(__file__).resolve().parent.parent / "data" / "rules.json"


def load_rules() -> dict:
    return json.loads(RULES_PATH.read_text(encoding="utf-8"))


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.strptime(value[:10], "%Y-%m-%d").date()


def assess_eligibility(
    registered: bool,
    enterprise_class: str,
    activity: str,
    nic_code: str = "",
    rules: dict | None = None,
) -> Eligibility:
    rules = rules or load_rules()
    klass = (enterprise_class or "").strip().lower()
    act = (activity or "").strip().lower()
    nic = (nic_code or "").strip()
    reasons: list[str] = []

    if not registered:
        reasons.append("Supplier registration (Udyam) is not confirmed.")
    if klass not in rules["eligible_classes"]:
        reasons.append("Delayed-payment provisions are described for micro and small enterprises, not medium.")
    if act in rules["ineligible_activities"]:
        reasons.append("Trading activity is treated as out of scope for this checklist.")
    nic_prefix = nic[:2] if nic else ""
    if nic_prefix in rules["ineligible_nic_prefixes"]:
        reasons.append(f"NIC code {nic} is in the trading range (45–47) used by this checklist.")

    return Eligibility(
        registered=registered,
        enterprise_class=klass,
        activity=act,
        nic_code=nic,
        eligible=len(reasons) == 0 and registered,
        reasons=reasons,
    )


def due_date_for(case: CasePackage, rules: dict | None = None) -> tuple[date, list[str]]:
    rules = rules or load_rules()
    caveats: list[str] = []
    start = parse_iso_date(case.accepted_date) or parse_iso_date(case.delivery_date) or parse_iso_date(
        case.invoice_date
    )
    if start is None:
        raise ValueError("invoice_date is required")
    if not case.accepted_date:
        caveats.append("Acceptance date missing; invoice or delivery date used as a stand-in (estimate, verify).")
    credit = min(int(case.agreed_credit_days or rules["max_credit_days"]), int(rules["max_credit_days"]))
    if int(case.agreed_credit_days or 0) > int(rules["max_credit_days"]):
        caveats.append("Agreed credit days exceed 45; checklist caps at 45 days (estimate, verify).")
    return start + timedelta(days=credit), caveats


def estimate_interest(
    case: CasePackage,
    as_of: date | None = None,
    rules: dict | None = None,
) -> InterestEstimate:
    rules = rules or load_rules()
    as_of = as_of or date.today()
    due, caveats = due_date_for(case, rules)
    caveats.append("All figures are estimates. Verify invoice records, acceptance date, and the current RBI bank rate.")
    overdue = (as_of - due).days
    principal = float(case.invoice_amount)
    bank_rate = float(rules["rbi_bank_rate"])
    annual = bank_rate * float(rules["interest_multiplier"])
    interest = 0.0
    if overdue > 0:
        monthly = annual / 12.0
        months = overdue // int(rules["day_count_month"])
        rem_days = overdue % int(rules["day_count_month"])
        accrued = principal * ((1 + monthly) ** months - 1)
        rem = (principal + accrued) * annual * rem_days / 365.0
        interest = round(accrued + rem, 2)
    else:
        overdue = 0
        caveats.append("Invoice does not appear overdue on the dates supplied (estimate, verify).")

    return InterestEstimate(
        principal=principal,
        currency=case.currency,
        due_date=due.isoformat(),
        as_of=as_of.isoformat(),
        overdue_days=overdue,
        rbi_bank_rate=bank_rate,
        rbi_bank_rate_as_of=str(rules["rbi_bank_rate_as_of"]),
        annual_rate=annual,
        interest=interest,
        total=round(principal + interest, 2),
        method="3 × RBI bank rate, compound monthly rests, remainder days simple/365 (estimate, verify)",
        label=ESTIMATE_LABEL,
        caveats=caveats,
    )


def _qty_mismatch(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return False
    return abs(float(left) - float(right)) > 0.001


def reconcile_case(case: CasePackage, mode: str = "full") -> ReconcileResult:
    findings: list[Finding] = []
    has_po = bool(case.po_no)
    has_grn = bool(case.grn_no or case.delivery_date)
    if not has_po:
        findings.append(Finding("missing_po", "warn", "Purchase order number is not on file."))
    if not has_grn:
        findings.append(
            Finding("missing_delivery", "block", "No delivery / GRN / acceptance proof is on file.")
        )
    if case.po_amount is not None and abs(float(case.po_amount) - float(case.invoice_amount)) > 0.01:
        findings.append(
            Finding(
                "po_amount_mismatch",
                "warn",
                f"PO amount {case.po_amount} does not match invoice amount {case.invoice_amount}.",
            )
        )
    for item in case.line_items:
        if _qty_mismatch(item.po_qty, item.qty):
            findings.append(
                Finding(
                    "po_qty_mismatch",
                    "warn",
                    f"SKU {item.sku}: invoice qty {item.qty} vs PO qty {item.po_qty}.",
                )
            )
        if _qty_mismatch(item.grn_qty, item.qty):
            findings.append(
                Finding(
                    "grn_qty_mismatch",
                    "warn",
                    f"SKU {item.sku}: invoice qty {item.qty} vs GRN qty {item.grn_qty}.",
                )
            )

    if mode == "lite":
        findings.append(
            Finding(
                "lite_mode",
                "info",
                "Lite reconciliation used because evidence is incomplete. Do not treat this as a confirmed three-way match.",
            )
        )

    evidence_complete = has_po and has_grn and not any(f.code == "po_qty_mismatch" for f in findings)
    blocked = any(f.severity == "block" for f in findings)
    matched = evidence_complete and not any(f.severity in {"warn", "block"} for f in findings)
    return ReconcileResult(
        mode=mode,
        matched=matched,
        evidence_complete=evidence_complete and not blocked,
        can_draft_payment_reminder=has_grn and not blocked,
        findings=findings,
    )


def pick_reconcile_mode(case: CasePackage) -> str:
    if case.po_no and (case.grn_no or case.delivery_date):
        return "full"
    return "lite"
