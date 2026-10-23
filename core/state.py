from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.audit import record_event
from core.calc import (
    RulesNotVerified,
    assess_eligibility,
    estimate_interest,
    get_effective_rules,
    load_rules,
    pick_reconcile_mode,
    reconcile_case,
)
from core.cards import case_carousel, eligibility_form, package_review
from core.guardrails import DISCLAIMER, DRAFT_BANNER, ESTIMATE_LABEL
from core.llm import (
    build_drafts,
    build_drafts_with_status,
    draft_violations,
    explain_evidence_gaps,
    parse_case_with_asi1,
)
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
from core.recovery import (
    FlakyReconciler,
    ReconcilerClient,
    ReconcilerTimeout,
    make_step_key,
    run_fallback_reconciliation,
)

CASES_DIR = Path(__file__).resolve().parent.parent / "data" / "cases"


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
    if "case 1" in lowered or "case1" in lowered:
        return {"action": "load_case", "case_id": "case1_clean"}
    if "case 2" in lowered or "case2" in lowered:
        return {"action": "load_case", "case_id": "case2_po_mismatch"}
    if "case 3" in lowered or "case3" in lowered:
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


def _extract_rules_used(rules: dict | None, keys: list[str]) -> list[dict[str, str]]:
    if not rules:
        return []
    result = []
    for k in keys:
        if k in rules:
            item = rules[k]
            src = item.get("source") if isinstance(item, dict) else "rules.json"
            result.append({"key": k, "source": str(src or "rules.json")})
    return result


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


def _run_pipeline(
    session: Session,
    rules: dict | None = None,
    reconciler: ReconcilerClient | None = None,
) -> Turn:
    assert session.case is not None
    eff_rules = rules or session.rules
    client = reconciler or FlakyReconciler()
    case = session.case
    case_id = case.case_id

    # 1. RECONCILE STEP
    rec_mode = session.reconcile.mode if session.reconcile else pick_reconcile_mode(case)
    rec_inputs = {
        "mode": rec_mode,
        "invoice_no": case.invoice_no,
        "invoice_amount": case.invoice_amount,
    }
    rec_key = make_step_key(case_id, "reconcile", rec_inputs)

    if session.reconcile is not None and "reconcile" in session.step_keys:
        # Step already marked done from checkpoint or fallback: skip execution and duplicate audit
        pass
    elif session.step_keys.get("reconcile") == rec_key and session.reconcile is not None:
        pass
    else:
        mode = pick_reconcile_mode(case)
        rec_result = None
        try:
            rec_result = client.reconcile(case, mode=mode)
        except ReconcilerTimeout:
            # Retry once on ReconcilerTimeout
            try:
                rec_result = client.reconcile(case, mode=mode)
            except ReconcilerTimeout:
                # Mark step failed, set to waiting-for-approval state
                session.failed_step = "reconcile"
                session.fallback_available = True
                session.fallback_mode = "lite"
                session.stage = "waiting_for_approval"
                record_event(
                    session=session,
                    step="reconcile",
                    actor="reconciler",
                    action="failed",
                    inputs=rec_inputs,
                    outputs={"error": "ReconcilerTimeout after 1 retry"},
                    approval_status="pending",
                )
                return Turn(
                    text=(
                        "Reconciler component timed out after 1 retry. The step has failed.\n\n"
                        "A rule-based fallback (mode \"lite\") can take over with fewer checks.\n"
                        "Do you approve running the fallback? Reply 'approve' to proceed, or 'refuse' to cancel."
                    ),
                    card_kind="approval",
                    card_payload={
                        "action": "fallback_approval",
                        "failed_component": "reconciler",
                        "fallback_mode": "lite",
                        "description": "Rule-based fallback with fewer checks.",
                    },
                )
        session.reconcile = rec_result
        session.step_keys["reconcile"] = rec_key
        record_event(
            session=session,
            step="reconcile",
            actor="reconciler",
            action="execute",
            inputs=rec_inputs,
            outputs={
                "mode": rec_result.mode,
                "matched": rec_result.matched,
                "evidence_complete": rec_result.evidence_complete,
            },
            approval_status=None,
        )

    # 2. ESTIMATE STEP
    est_inputs = {
        "invoice_amount": case.invoice_amount,
        "invoice_date": case.invoice_date,
        "accepted_date": case.accepted_date,
        "agreed_credit_days": case.agreed_credit_days,
    }
    est_key = make_step_key(case_id, "estimate", est_inputs)

    if session.step_keys.get("estimate") == est_key and session.estimate is not None:
        pass
    else:
        session.estimate = estimate_interest(case, rules=eff_rules)
        session.step_keys["estimate"] = est_key
        rules_used = _extract_rules_used(
            eff_rules,
            ["rbi_bank_rate", "interest_multiplier", "day_count_month", "max_credit_days"],
        )
        record_event(
            session=session,
            step="estimate",
            actor="orchestrator",
            action="execute",
            inputs=est_inputs,
            outputs={
                "interest": session.estimate.interest,
                "total": session.estimate.total,
                "label": session.estimate.label,
            },
            rules_used=rules_used,
            approval_status=None,
        )

    # 3. DRAFT STEP
    draft_inputs = {
        "interest": session.estimate.interest if session.estimate else 0,
        "reconcile_mode": session.reconcile.mode if session.reconcile else "",
        "can_draft_payment_reminder": session.reconcile.can_draft_payment_reminder if session.reconcile else False,
    }
    draft_key = make_step_key(case_id, "draft", draft_inputs)
    used_asi1_draft = False

    if session.step_keys.get("draft") == draft_key and session.drafts:
        pass
    else:
        session.drafts, used_asi1_draft = build_drafts_with_status(case, session.estimate, session.reconcile, rules=eff_rules, use_llm=True)
        for draft in session.drafts:
            if draft_violations(draft.body, rules=eff_rules):
                draft.body = f"{DRAFT_BANNER}\n\nDraft blocked by language guardrail. Factual template required."
        session.step_keys["draft"] = draft_key
        record_event(
            session=session,
            step="draft",
            actor="drafter",
            action="execute",
            inputs=draft_inputs,
            outputs={"draft_count": len(session.drafts), "kinds": [d.kind for d in session.drafts], "used_asi1": used_asi1_draft},
            approval_status=None,
        )

    session.stage = "review"
    drafts_text = "\n\n".join(f"[{d.kind}] {d.subject}\n{d.body}" for d in session.drafts)
    estimate = session.estimate
    rec = session.reconcile
    gaps_note = ""
    if rec.findings:
        gaps_exp, _ = explain_evidence_gaps(rec.findings, case)
        gaps_note = f"\nEvidence check: {gaps_exp}\n"
    llm_status_note = "" if used_asi1_draft else "\n(Drafts prepared using template fallback: ASI1 unavailable or failed.)\n"
    return Turn(
        text=(
            f"Working file ready (drafts unsent).\n"
            f"Interest {estimate.currency} {estimate.interest:.2f} — {estimate.label}.\n"
            f"Reconcile mode: {rec.mode}. Payment-reminder draft allowed: {rec.can_draft_payment_reminder}.\n"
            f"{gaps_note}{llm_status_note}\n"
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
    session: Session,
    user_text: str,
    rules: dict | None = None,
    reconciler: ReconcilerClient | None = None,
) -> tuple[Session, Turn]:
    if rules is not None:
        session.rules = rules
    if session.rules is None:
        session.rules = get_effective_rules()
    eff_rules = session.rules
    client = reconciler or FlakyReconciler()

    payload = parse_payload(user_text)
    action = str(payload.get("action") or "")

    # Reset
    if action == "reset" or user_text.strip().lower() == "reset":
        saved_rules = session.rules
        session = Session()
        session.rules = saved_rules
        session.stage = "eligibility"
        return session, _welcome(eff_rules)

    # Waiting for approval state handling (Retry & Fallback gate)
    if session.stage in {"waiting_for_approval", "fallback_approval"}:
        lowered = user_text.strip().lower()
        is_approval = action in {"approve", "approve_fallback"} or any(
            w in lowered for w in ["approve", "yes", "accept", "proceed", "confirm"]
        )
        is_refusal = action in {"refuse", "refuse_fallback", "reject", "cancel"} or any(
            w in lowered for w in ["refuse", "no", "reject", "cancel"]
        )

        if is_approval:
            record_event(
                session=session,
                step="fallback_approval",
                actor="user",
                action="approval",
                inputs={"choice": "approve", "fallback_mode": "lite"},
                outputs={"decision": "fallback_accepted"},
                approval_status="approved",
            )
            # Execute rule-based fallback in mode "lite"
            session.reconcile = run_fallback_reconciliation(session.case)
            rec_inputs = {
                "mode": "lite",
                "invoice_no": session.case.invoice_no,
                "invoice_amount": session.case.invoice_amount,
            }
            session.step_keys["reconcile"] = make_step_key(session.case.case_id, "reconcile", rec_inputs)
            record_event(
                session=session,
                step="reconcile",
                actor="orchestrator",
                action="fallback",
                inputs=rec_inputs,
                outputs={"mode": "lite", "notes": session.reconcile.notes},
                approval_status="approved",
            )
            session.failed_step = None
            session.fallback_available = False
            session.stage = "work"
            return session, _run_pipeline(session, rules=eff_rules, reconciler=client)

        if is_refusal:
            record_event(
                session=session,
                step="fallback_approval",
                actor="user",
                action="approval",
                inputs={"choice": "refuse"},
                outputs={"decision": "fallback_refused"},
                approval_status="refused",
            )
            session.stage = "ended"
            session.failed_step = None
            session.fallback_available = False
            return session, Turn(
                "Session ended. Fallback was refused. No further processing performed."
            )

        return session, Turn(
            "A waiting-for-approval decision is required.\n"
            "Please reply 'approve' to proceed with rule-based fallback (mode lite, fewer checks) or 'refuse' to cancel."
        )

    # Scheme readiness
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

    # Credit query
    if Planner.is_credit_query(user_text):
        steps = Planner.get_recommended_steps(user_text, session)
        steps_list = "\n".join(f"{i+1}. {step}" for i, step in enumerate(steps))
        return session, Turn(
            f"Recommended next steps:\n{steps_list}\n\n"
            "Scheme readiness reviews document checklists for official schemes (MUDRA, PMEGP, Stand-Up India, CGTMSE). "
            f"{CHECKLIST_LABEL}.\n"
            "Explicit user consent and confirmation are required before producing the checklist."
        )

    # Initial start stage
    if session.stage == "start":
        lowered_txt = user_text.lower()
        if any(w in lowered_txt for w in ["registered", "udyam", "micro", "small"]):
            session.stage = "eligibility"
        else:
            session.stage = "eligibility"
            return session, _welcome(eff_rules)

    if action == "help":
        return session, Turn(
            "Tell me whether the supplier is Udyam-registered (micro/small, manufacturing or services). "
            "Then load case1, case2, or case3, or paste invoice JSON. Drafts stay unsent."
        )

    if session.stage == "blocked":
        lowered_txt = user_text.lower()
        if any(w in lowered_txt for w in ["registered", "udyam", "micro", "small"]):
            session.stage = "eligibility"
        else:
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
            record_event(
                session=session,
                step="eligibility",
                actor="orchestrator",
                action="execute",
                inputs={"registered": registered, "class": klass, "activity": activity, "nic": nic},
                outputs={"eligible": session.eligibility.eligible, "reasons": session.eligibility.reasons},
                rules_used=_extract_rules_used(eff_rules, ["registration_required", "eligible_classes", "ineligible_activities"]),
                approval_status=None,
            )
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
        return session, _run_pipeline(session, rules=eff_rules, reconciler=client)

    if session.stage == "intake" and "invoice_no" in payload:
        session.case = case_from_dict(payload)
        session.stage = "work"
        return session, _run_pipeline(session, rules=eff_rules, reconciler=client)

    if session.stage == "intake" and action == "text":
        parsed_case, used_asi1 = parse_case_with_asi1(user_text)
        if parsed_case is not None:
            session.case = parsed_case
            session.stage = "work"
            turn = _run_pipeline(session, rules=eff_rules, reconciler=client)
            fallback_msg = "" if used_asi1 else " (case parsed via template fallback)"
            turn.text = f"Case extracted from text{fallback_msg}.\n\n" + turn.text
            return session, turn

    # Draft finalization approval gate
    if session.stage == "review" and action == "keep_package":
        session.stage = "done"
        record_event(
            session=session,
            step="finalize_draft",
            actor="user",
            action="approval",
            inputs={"action": "keep_package", "case_id": session.case.case_id if session.case else None},
            outputs={"status": "kept_for_review"},
            approval_status="approved",
        )
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
