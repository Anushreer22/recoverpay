from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


ESTIMATE_LABEL = "estimate, verify"


def to_dict(obj: Any) -> Any:
    if hasattr(obj, "__dataclass_fields__"):
        return {k: to_dict(v) for k, v in asdict(obj).items()}
    if isinstance(obj, list):
        return [to_dict(v) for v in obj]
    return obj


@dataclass
class Party:
    name: str
    gstin: str | None = None
    state: str | None = None
    udyam: str | None = None
    enterprise_class: str | None = None
    activity: str | None = None
    nic_code: str | None = None
    contact_email: str | None = None


@dataclass
class LineItem:
    sku: str
    description: str
    qty: float
    unit_price: float
    po_qty: float | None = None
    grn_qty: float | None = None


@dataclass
class CasePackage:
    case_id: str
    supplier: Party
    buyer: Party
    invoice_no: str
    invoice_date: str
    invoice_amount: float
    currency: str = "INR"
    po_no: str | None = None
    po_date: str | None = None
    po_amount: float | None = None
    grn_no: str | None = None
    delivery_date: str | None = None
    accepted_date: str | None = None
    agreed_credit_days: int = 45
    line_items: list[LineItem] = field(default_factory=list)
    notes: str = ""


@dataclass
class Finding:
    code: str
    severity: str
    message: str


@dataclass
class ReconcileResult:
    mode: str
    matched: bool
    evidence_complete: bool
    can_draft_payment_reminder: bool
    findings: list[Finding] = field(default_factory=list)


@dataclass
class InterestEstimate:
    principal: float
    currency: str
    due_date: str
    as_of: str
    overdue_days: int
    rbi_bank_rate: float
    rbi_bank_rate_as_of: str
    annual_rate: float
    interest: float
    total: float
    method: str
    label: str
    caveats: list[str] = field(default_factory=list)


@dataclass
class Draft:
    kind: str
    subject: str
    body: str
    for_review_only: bool = True


@dataclass
class Eligibility:
    registered: bool
    enterprise_class: str
    activity: str
    nic_code: str
    eligible: bool
    reasons: list[str] = field(default_factory=list)


@dataclass
class Session:
    stage: str = "start"
    eligibility: Eligibility | None = None
    case: CasePackage | None = None
    reconcile: ReconcileResult | None = None
    estimate: InterestEstimate | None = None
    drafts: list[Draft] = field(default_factory=list)


def party_from_dict(data: dict[str, Any]) -> Party:
    return Party(**{k: data[k] for k in Party.__dataclass_fields__ if k in data})


def case_from_dict(data: dict[str, Any]) -> CasePackage:
    payload = dict(data)
    supplier = party_from_dict(payload.pop("supplier"))
    buyer = party_from_dict(payload.pop("buyer"))
    items = [LineItem(**item) for item in payload.pop("line_items", [])]
    allowed = set(CasePackage.__dataclass_fields__)
    return CasePackage(
        supplier=supplier,
        buyer=buyer,
        line_items=items,
        **{k: v for k, v in payload.items() if k in allowed},
    )


def session_from_dict(data: dict[str, Any] | None) -> Session:
    if not data:
        return Session()
    elig = data.get("eligibility")
    case = data.get("case")
    rec = data.get("reconcile")
    est = data.get("estimate")
    drafts = data.get("drafts") or []
    return Session(
        stage=data.get("stage") or "start",
        eligibility=Eligibility(**elig) if elig else None,
        case=case_from_dict(case) if case else None,
        reconcile=ReconcileResult(
            **{**rec, "findings": [Finding(**f) for f in rec.get("findings", [])]}
        )
        if rec
        else None,
        estimate=InterestEstimate(**est) if est else None,
        drafts=[Draft(**d) for d in drafts],
    )


def session_to_dict(session: Session) -> dict[str, Any]:
    return to_dict(session)
