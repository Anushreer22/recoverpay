from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.calc import (
    RulesNotVerified,
    assess_eligibility,
    estimate_interest,
    load_rules,
    pick_reconcile_mode,
    reconcile_case,
)
from core.cards import case_carousel, eligibility_form, package_review
from core.guardrails import DISCLAIMER, DRAFT_BANNER, ESTIMATE_LABEL
from core.llm import build_drafts, draft_violations
from core.models import CasePackage, Session, case_from_dict
from core.planner import Planner, get_recommended_steps
from core.readiness import (
    CHECKLIST_LABEL,
    ConsentRequired,
    Profile,
    ReadinessResult,
    SchemeRulesNotVerified,
    load_schemes,
    readiness_checklist,
    render_checklist,
)

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
    if "scheme_readiness" in lowered or "scheme readiness" in lowered:
        return {"action": "scheme_readiness", "text": raw}
    return {"action": "text", "text": raw}


def _get_disclaimer(rules: dict | None = None) -> str:
    rules = rules or load_rules()
    disclaimer_val = rules.get("disclaimer")
    if isinstance(disclaimer_val, dict):
        return disclaimer_val.get("value") or DISCLAIMER
    return disclaimer_val or DISCLAIMER


def _welcome(rules: dict | None = None) -> Turn:
    disclaimer = _get_disclaimer(rules)
    return Turn(
        text=(
            "RecoverPay prepares overdue-invoice case packages for Indian MSME suppliers.\n"
            f"{disclaimer}\n\n"
            "Before any calculation or draft, confirm supplier registration and eligibility."
        ),
        card_kind="form",
        card_payload=eligibility_form(),
    )


def _run_pipeline(session: Session, rules: dict | None = None) -> Turn:
    assert session.case is not None
    eff_rules = rules or session.rules
    mode = pick_reconcile_mode(session.case)
    session.reconcile = reconcile_case(session.case, mode=mode)
    session.estimate = estimate_interest(session.case, rules=eff_rules)
    session.drafts = build_drafts(session.case, session.estimate, session.reconcile, rules=eff_rules)
    for draft in session.drafts:
        if draft_violations(draft.body, rules=eff_rules):
            draft.body = f"{DRAFT_BANNER}\n\nDraft blocked by language guardrail. Factual template required."
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


def produce_scheme_readiness_turn(
    profile: Profile,
    scheme_name: str,
    schemes: Any = None,
    user_approved: bool = False,
) -> Turn:
    if not user_approved:
        return Turn(
            "User confirmation required before producing checklist. "
            "Please confirm to proceed with scheme readiness check."
        )
    try:
        schemes_data = schemes or load_schemes()
        result = readiness_checklist(profile, scheme_name, schemes_data)
        return Turn(render_checklist(result))
    except SchemeRulesNotVerified as exc:
        return Turn(
            f"Scheme rules not verified: {exc}. "
            "Fill from the official scheme guidelines with the exact URL. Do not guess."
        )
    except ConsentRequired as exc:
        return Turn(f"Consent required: {exc}")


def handle_turn(
    session: Session, user_text: str, rules: dict | None = None
) -> tuple[Session, Turn]:
    if rules is not None:
        session.rules = rules
    eff_rules = rules or session.rules

    payload = parse_payload(user_text)
    action = str(payload.get("action") or "")

    if action == "reset" or user_text.strip().lower() == "reset":
        saved_rules = session.rules
        session = Session()
        session.rules = saved_rules
        session.stage = "eligibility"
        return session, _welcome(eff_rules)

    if action == "scheme_readiness":
        scheme_name = str(payload.get("scheme") or payload.get("scheme_name") or "MUDRA")
        if "consent" in payload:
            consent = bool(payload["consent"])
        else:
            consent = "consent" in user_text.lower()

        if "approve" in payload:
            approved = bool(payload["approve"])
        elif "approval" in payload:
            approved = bool(payload["approval"])
        elif "approved" in payload:
            approved = bool(payload["approved"])
        else:
            approved = "approve" in user_text.lower() or "confirm" in user_text.lower()

        if not consent:
            return session, Turn(
                "Consent required before producing checklist. "
                "Explicit user consent is mandatory for scheme readiness review."
            )
        if not approved:
            return session, Turn(
                "User confirmation required before producing checklist. "
                "Please confirm to proceed with scheme readiness check."
            )

        schemes_data = payload.get("schemes") or load_schemes()
        profile = session.profile or Profile(
            business_type="micro",
            registration_status="registered",
            documents_held=[],
            consent_given=consent,
        )

        turn = produce_scheme_readiness_turn(
            profile=profile,
            scheme_name=scheme_name,
            schemes=schemes_data,
            user_approved=approved,
        )
        session.consent_given = consent
        return session, turn

    if Planner.is_credit_query(user_text):
        steps = Planner.get_recommended_steps(user_text, session)
        steps_list = "\n".join(f"{i+1}. {step}" for i, step in enumerate(steps))
        return session, Turn(
            f"Recommended next steps:\n{steps_list}\n\n"
            "Scheme readiness reviews document checklists for official schemes (MUDRA, PMEGP, Stand-Up India, CGTMSE). "
            f"{CHECKLIST_LABEL}.\n"
            "Explicit user consent and confirmation are required before producing the checklist."
        )

    if session.stage == "start":
        session.stage = "eligibility"
        return session, _welcome(eff_rules)

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

        try:
            session.eligibility = assess_eligibility(registered, klass, activity, nic, rules=eff_rules)
        except RulesNotVerified as exc:
            session.stage = "blocked"
            return session, Turn(
                f"Stopped before calculations. Rules not verified: {exc}."
            )

        if not session.eligibility.eligible:
            session.stage = "blocked"
            reasons = " ".join(session.eligibility.reasons)
            return session, Turn(
                f"Stopped before calculations. {reasons} "
                f"{_get_disclaimer(eff_rules)}"
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
        return session, _run_pipeline(session, rules=eff_rules)

    if session.stage == "intake" and "invoice_no" in payload:
        session.case = case_from_dict(payload)
        session.stage = "work"
        return session, _run_pipeline(session, rules=eff_rules)

    if session.stage == "review" and action == "keep_package":
        session.stage = "done"
        return session, Turn(
            "Package kept for the supplier's review. Nothing was sent to the buyer or to any portal."
        )

    if session.stage == "eligibility":
        return session, _welcome(eff_rules)

    return session, Turn(
        "I can check eligibility, load case1/case2/case3, or rebuild a package. Nothing is auto-sent."
    )


# Backwards-friendly alias if tests import Reply from core.models later.
Reply = Turn
