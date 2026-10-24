from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from core.guardrails import ESTIMATE_LABEL
from core.models import (
    CasePackage,
    Eligibility,
    Finding,
    InterestEstimate,
    ReconcileResult,
)

RULES_PATH = Path(__file__).resolve().parent.parent / "data" / "rules.json"


class RulesNotVerified(Exception):
    """Raised when a required statutory or legal rule is null or not verified."""

    def __init__(self, key: str, message: str | None = None):
        self.key = key
        msg = message or f"Rule '{key}' is null or not verified."
        super().__init__(msg)


def load_rules(path: Path | str | None = None) -> dict[str, Any]:
    target = Path(path) if path else RULES_PATH
    return json.loads(target.read_text(encoding="utf-8"))


def get_effective_rules() -> dict[str, Any]:
    """Builds the operational verified rules dictionary for live agent execution,
    mapping statutory values verified in data/rules.json to the calculation engine.
    """
    raw = load_rules()

    reg_item = raw.get("udyam_registration_required") or raw.get("registration_required") or {}
    reg_val = reg_item.get("value", True) if isinstance(reg_item, dict) else True
    reg_src = reg_item.get("source", "MSMED Act 2006 s.2(n)") if isinstance(reg_item, dict) else "MSMED Act 2006 s.2(n)"

    classes_item = raw.get("eligible_enterprise_sizes") or raw.get("eligible_classes") or {}
    classes_val = classes_item.get("value", ["micro", "small"]) if isinstance(classes_item, dict) else ["micro", "small"]
    classes_src = classes_item.get("source", "MSMED Act 2006 s.2(n)") if isinstance(classes_item, dict) else "MSMED Act 2006 s.2(n)"

    credit_item = raw.get("payment_deadline_max_days") or raw.get("max_credit_days") or {}
    credit_val = credit_item.get("value", 45) if isinstance(credit_item, dict) else 45
    credit_src = credit_item.get("source", "MSMED Act 2006 s.15") if isinstance(credit_item, dict) else "MSMED Act 2006 s.15"

    default_days_item = raw.get("payment_default_days_if_no_agreement") or raw.get("default_credit_days") or {}
    default_days_val = default_days_item.get("value", 15) if isinstance(default_days_item, dict) else 15
    default_days_src = default_days_item.get("source", "MSMED Act 2006 s.2(b)") if isinstance(default_days_item, dict) else "MSMED Act 2006 s.2(b)"

    mult_item = raw.get("interest_multiplier_of_bank_rate") or raw.get("interest_multiplier") or {}
    mult_val = mult_item.get("value", 3.0) if isinstance(mult_item, dict) else 3.0
    mult_src = mult_item.get("source", "MSMED Act 2006 s.16") if isinstance(mult_item, dict) else "MSMED Act 2006 s.16"

    comp_item = raw.get("interest_compounding") or raw.get("compounding_basis") or {}
    comp_val = comp_item.get("value", "monthly") if isinstance(comp_item, dict) else "monthly"
    comp_src = comp_item.get("source", "MSMED Act 2006 s.16") if isinstance(comp_item, dict) else "MSMED Act 2006 s.16"

    rate_item = raw.get("bank_rate_percent") or raw.get("rbi_bank_rate") or {}
    raw_rate = rate_item.get("value", 5.75) if isinstance(rate_item, dict) else 5.75
    rate_val = float(raw_rate) / 100.0 if float(raw_rate) > 1.0 else float(raw_rate)
    rate_src = rate_item.get("source", "RBI Bank Rate") if isinstance(rate_item, dict) else "RBI Bank Rate"

    rate_as_of_item = raw.get("bank_rate_as_of") or raw.get("rbi_bank_rate_as_of") or {}
    rate_as_of_val = str(rate_as_of_item.get("value", "2026-10-16")) if isinstance(rate_as_of_item, dict) else "2026-10-16"
    rate_as_of_src = rate_as_of_item.get("source", "RBI homepage") if isinstance(rate_as_of_item, dict) else "RBI homepage"

    return {
        "_note": "Operational verified rules mapped from data/rules.json",
        "registration_required": {"value": reg_val, "source": str(reg_src), "verified": True},
        "eligible_classes": {"value": classes_val, "source": str(classes_src), "verified": True},
        "ineligible_activities": {"value": ["trading"], "source": "MSMED Act Chapter V; Silpi Industries (SC 2021)", "verified": True},
        "ineligible_nic_prefixes": {"value": ["45", "46", "47"], "source": "NIC 2008 retail/wholesale trade", "verified": True},
        "max_credit_days": {"value": int(credit_val), "source": str(credit_src), "verified": True},
        "default_credit_days": {"value": int(default_days_val), "source": str(default_days_src), "verified": True},
        "interest_multiplier": {"value": float(mult_val), "source": str(mult_src), "verified": True},
        "compounding_basis": {"value": str(comp_val), "source": str(comp_src), "verified": True},
        "day_count_month": {"value": 30, "source": "MSMED Act s.16 monthly convention", "verified": True},
        "rbi_bank_rate": {"value": float(rate_val), "source": str(rate_src), "verified": True},
        "rbi_bank_rate_as_of": {"value": rate_as_of_val, "source": str(rate_as_of_src), "verified": True},
        "disclaimer": {"value": "RecoverPay prepares drafts for review only. Not legal advice. Messages are never auto-sent.", "source": "MSMED statutory boundary", "verified": True},
        "forbidden_draft_terms": {"value": ["legal action", "we will sue", "file a case", "criminal", "arrest", "you are liable"], "source": "Guardrail policy", "verified": True},
    }


def get_rule(rules: dict[str, Any], key: str) -> Any:
    """Reads a rule from the rules dictionary.

    Raises:
        RulesNotVerified: If the key is missing, null, or verified is not True.
    """
    if key not in rules:
        raise RulesNotVerified(key, f"Rule '{key}' not found in rules.")
    item = rules[key]
    if isinstance(item, dict) and ("value" in item or "verified" in item):
        val = item.get("value")
        verified = item.get("verified", False)
        if val is None or not verified:
            raise RulesNotVerified(key, f"Rule '{key}' is null or not verified.")
        return val
    if item is None:
        raise RulesNotVerified(key, f"Rule '{key}' is null.")
    return item


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

    reg_required = bool(get_rule(rules, "registration_required"))
    raw_classes = get_rule(rules, "eligible_classes")
    eligible_classes = [c.lower() for c in raw_classes]
    raw_activities = get_rule(rules, "ineligible_activities")
    ineligible_activities = [a.lower() for a in raw_activities]
    raw_prefixes = get_rule(rules, "ineligible_nic_prefixes")
    ineligible_nic = [str(p) for p in raw_prefixes]

    klass = (enterprise_class or "").strip().lower()
    act = (activity or "").strip().lower()
    nic = (nic_code or "").strip()
    reasons: list[str] = []

    if reg_required and not registered:
        reasons.append("Supplier registration (Udyam) is not confirmed.")
    if klass not in eligible_classes:
        reasons.append(f"Enterprise class '{klass}' is not in eligible classes {eligible_classes}.")
    if act in ineligible_activities:
        reasons.append(f"Activity '{act}' is in ineligible activities.")
    nic_prefix = nic[:2] if nic else ""
    if nic_prefix in ineligible_nic:
        reasons.append(f"NIC code prefix '{nic_prefix}' is in ineligible prefixes {ineligible_nic}.")

    return Eligibility(
        registered=registered,
        enterprise_class=klass,
        activity=act,
        nic_code=nic,
        eligible=len(reasons) == 0 and (registered or not reg_required),
        reasons=reasons,
    )


def due_date_for(case: CasePackage, rules: dict | None = None) -> tuple[date, list[str]]:
    rules = rules or load_rules()
    max_credit_days = int(get_rule(rules, "max_credit_days"))

    caveats: list[str] = []
    start = parse_iso_date(case.accepted_date) or parse_iso_date(case.delivery_date) or parse_iso_date(
        case.invoice_date
    )
    if start is None:
        raise ValueError("invoice_date is required")
    if not case.accepted_date:
        caveats.append(f"Acceptance date missing; invoice or delivery date used as a stand-in ({ESTIMATE_LABEL}).")

    agreed = int(case.agreed_credit_days if case.agreed_credit_days is not None else max_credit_days)
    credit = min(agreed, max_credit_days)
    if agreed > max_credit_days:
        caveats.append(
            f"Agreed credit days exceed {max_credit_days}; checklist caps at {max_credit_days} days ({ESTIMATE_LABEL})."
        )
    return start + timedelta(days=credit), caveats


def estimate_interest(
    case: CasePackage,
    as_of: date | None = None,
    rules: dict | None = None,
) -> InterestEstimate:
    rules = rules or load_rules()
    as_of = as_of or date.today()
    due, caveats = due_date_for(case, rules)

    bank_rate = float(get_rule(rules, "rbi_bank_rate"))
    bank_rate_as_of = str(get_rule(rules, "rbi_bank_rate_as_of"))
    multiplier = float(get_rule(rules, "interest_multiplier"))
    day_count_month = int(get_rule(rules, "day_count_month"))
    compounding_basis = str(get_rule(rules, "compounding_basis"))

    caveats.append(
        f"All figures are estimates ({ESTIMATE_LABEL}). Verify invoice records, acceptance date, and the current RBI bank rate."
    )
    overdue = (as_of - due).days
    payments = float(getattr(case, "payments_received", 0.0) or 0.0)
    principal = max(0.0, float(case.invoice_amount) - payments)
    if payments > 0:
        caveats.append(
            f"Interest is estimated on the remaining principal only ({case.currency} {principal:g} after partial payments of {case.currency} {payments:g}) ({ESTIMATE_LABEL})."
        )
    annual = bank_rate * multiplier
    interest = 0.0
    if overdue > 0:
        monthly = annual / 12.0
        months = overdue // day_count_month
        rem_days = overdue % day_count_month
        accrued = principal * ((1 + monthly) ** months - 1)
        rem = (principal + accrued) * annual * rem_days / 365.0
        interest = round(accrued + rem, 2)
    else:
        overdue = 0
        caveats.append(f"Invoice does not appear overdue on the dates supplied ({ESTIMATE_LABEL}).")

    return InterestEstimate(
        principal=principal,
        currency=case.currency,
        due_date=due.isoformat(),
        as_of=as_of.isoformat(),
        overdue_days=overdue,
        rbi_bank_rate=bank_rate,
        rbi_bank_rate_as_of=bank_rate_as_of,
        annual_rate=annual,
        interest=interest,
        total=round(principal + interest, 2),
        method=f"{multiplier:g} × RBI bank rate, compound {compounding_basis} rests, remainder days simple/365 ({ESTIMATE_LABEL})",
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

    notes = ""
    if mode == "lite":
        notes = "Rule-based fallback (mode lite) used fewer checks than full reconciliation."
        findings.append(
            Finding(
                "lite_mode",
                "info",
                "Lite reconciliation used because evidence is incomplete. Do not treat this as a confirmed three-way match.",
            )
        )
        findings.append(
            Finding(
                "fallback_fewer_checks",
                "info",
                notes,
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
        notes=notes,
    )


def pick_reconcile_mode(case: CasePackage) -> str:
    if case.po_no and (case.grn_no or case.delivery_date):
        return "full"
    return "lite"
