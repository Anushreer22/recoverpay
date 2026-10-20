from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.calc import (
    assess_eligibility,
    estimate_interest,
    load_rules,
    pick_reconcile_mode,
    reconcile_case,
)
from core.cards import case_carousel, eligibility_form, package_review
from core.llm import build_drafts, draft_violations
from core.models import CasePackage, Session, case_from_dict

CASES_DIR = Path(__file__).resolve().parent.parent / "data" / "cases"


# Reply is used by tests and the orchestrator. Defined here to keep state.py the API.
class Turn:
    def __init__(self, text: str, card_kind: str | None = None, card_payload: dict[str, Any] | None = None):
        self.text = text
        self.card_kind = card_kind
        self.card_payload = card_payload


def load_case(case_id: str) -> CasePackage:
    path = CASES_DIR / f"{case_id}.json"
    if not path.exists():
        raise FileNotFoundError(case_id)
    return case_from_dict(json.loads(path.read_text(encoding="utf-8")))


def parse_payload(text: str) -> dict[str, Any]:
    raw = text.strip()
    if raw.startswith("{") and raw.endswith("}"):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    lowered = raw.lower()
    if lowered in {"reset", "start over", "restart"}:
        return {"action": "reset"}
    if lowered in {"help", "hi", "hello"}:
        return {"action": "help"}
    for case_id in ("case1_clean", "case2_po_mismatch", "case3_no_delivery_proof"):
        if case_id in lowered or case_id.replace("_", " ") in lowered:
            return {"action": "load_case", "case_id": case_id}
    if "case 1" in lowered or lowered == "case1":
        return {"action": "load_case", "case_id": "case1_clean"}
    if "case 2" in lowered or lowered == "case2":
        return {"action": "load_case", "case_id": "case2_po_mismatch"}
    if "case 3" in lowered or lowered == "case3":
        return {"action": "load_case", "case_id": "case3_no_delivery_proof"}
    return {"action": "text", "text": raw}


def _welcome() -> Turn:
    rules = load_rules()
    return Turn(
        text=(
            "RecoverPay prepares overdue-invoice case packages for Indian MSME suppliers.\n"
            f"{rules['disclaimer']}\n\n"
            "Before any calculation or draft, confirm supplier registration and eligibility."
        ),
        card_kind="form",
        card_payload=eligibility_form(),
    )


def _run_pipeline(session: Session) -> Turn:
    assert session.case is not None
    mode = pick_reconcile_mode(session.case)
    session.reconcile = reconcile_case(session.case, mode=mode)
    session.estimate = estimate_interest(session.case)
    session.drafts = build_drafts(session.case, session.estimate, session.reconcile)
    for draft in session.drafts:
        if draft_violations(draft.body):
            draft.body = "Draft blocked by language guardrail. Factual template required."
    session.stage = "review"
    drafts_text = "\n\n".join(f"[{d.kind}] {d.subject}\n{d.body}" for d in session.drafts)
    estimate = session.estimate
    rec = session.reconcile
    return Turn(
        text=(
            f"Working file ready (drafts unsent).\n"
            f"Interest {estimate.currency} {estimate.interest:.2f} — {estimate.label}.\n"
            f"Reconcile mode: {rec.mode}. Payment-reminder draft allowed: {rec.can_draft_payment_reminder}.\n\n"
            f"{drafts_text}"
        ),
        card_kind="review",
        card_payload=package_review(session.case, estimate, rec, session.drafts),
    )


def handle_turn(session: Session, user_text: str) -> tuple[Session, Turn]:
    payload = parse_payload(user_text)
    action = str(payload.get("action") or "")

    if action == "reset" or user_text.strip().lower() == "reset":
        session = Session()
        session.stage = "eligibility"
        return session, _welcome()

    if session.stage == "start":
        session.stage = "eligibility"
        return session, _welcome()

    if action == "help":
        return session, Turn(
            "Tell me whether the supplier is Udyam-registered (micro/small, manufacturing or services). "
            "Then load case1, case2, or case3, or paste invoice JSON. Drafts stay unsent."
        )

    if session.stage == "blocked":
        return session, Turn(
            "This file is out of scope until supplier registration/eligibility is confirmed. "
            "Send reset to start again."
        )

    if session.stage == "eligibility" and action == "load_case":
        return session, Turn(
            "Confirm supplier registration and eligibility before loading a case.",
            card_kind="form",
            card_payload=eligibility_form(),
        )

    if session.stage == "eligibility" and action in {"eligibility", "text"}:
        registered_raw = str(payload.get("registered") or payload.get("text") or "").lower()
        registered = registered_raw in {"yes", "true", "y", "registered"}
        if action == "text" and "not" in registered_raw:
            registered = False
        klass = str(payload.get("enterprise_class") or "micro")
        activity = str(payload.get("activity") or "manufacturing")
        nic = str(payload.get("nic_code") or "")
        if action == "text":
            text = registered_raw
            if "medium" in text:
                klass = "medium"
            if "trading" in text:
                activity = "trading"
            if "small" in text:
                klass = "small"
            if "micro" in text:
                klass = "micro"
            if "service" in text:
                activity = "services"
            if "udyam" in text or "registered" in text:
                registered = "not" not in text and "no" not in text.split()
        session.eligibility = assess_eligibility(registered, klass, activity, nic)
        if not session.eligibility.eligible:
            session.stage = "blocked"
            reasons = " ".join(session.eligibility.reasons)
            return session, Turn(
                f"Stopped before calculations. {reasons} "
                f"{load_rules()['disclaimer']}"
            )
        session.stage = "intake"
        return session, Turn(
            "Eligibility recorded for this working file. Choose a demo case or send case JSON.",
            card_kind="carousel",
            card_payload=case_carousel(),
        )

    if session.stage in {"intake", "review"} and action == "load_case":
        session.case = load_case(str(payload["case_id"]))
        session.stage = "work"
        return session, _run_pipeline(session)

    if session.stage == "intake" and "invoice_no" in payload:
        session.case = case_from_dict(payload)
        session.stage = "work"
        return session, _run_pipeline(session)

    if session.stage == "review" and action == "keep_package":
        session.stage = "done"
        return session, Turn(
            "Package kept for the supplier's review. Nothing was sent to the buyer or to any portal."
        )

    if session.stage == "eligibility":
        return session, _welcome()

    return session, Turn(
        "I can check eligibility, load case1/case2/case3, or rebuild a package. Nothing is auto-sent."
    )


# Backwards-friendly alias if tests import Reply from core.models later.
Reply = Turn
