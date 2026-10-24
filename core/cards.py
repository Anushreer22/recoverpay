from __future__ import annotations

import json
from typing import Any

from uagents_core.contrib.protocols.chat import (
    ChatMessage,
    MetadataContent,
    TextContent,
)

from core.calc import load_rules
from core.guardrails import DISCLAIMER
from core.models import CasePackage, Draft, InterestEstimate, ReconcileResult


def card_message(narration: str, card_kind: str, card_payload: dict[str, Any]) -> ChatMessage:
    return ChatMessage(
        content=[
            TextContent(type="text", text=narration),
            MetadataContent(
                metadata={
                    "card_protocol_version": "1",
                    "requires_card_interaction": "true",
                    "card_kind": card_kind,
                    "card_payload": json.dumps(card_payload),
                    "preferred_drawer_width_px": "540",
                }
            ),
        ]
    )


def eligibility_form() -> dict[str, Any]:
    return {
        "title": "Supplier registration check",
        "subtitle": "Confirm eligibility before any overdue working. Drafts only — not legal advice.",
        "fields": [
            {
                "name": "registered",
                "kind": "select",
                "label": "Udyam / MSME registration?",
                "required": True,
                "options": [
                    {"value": "yes", "label": "Yes, registered"},
                    {"value": "no", "label": "No / not sure"},
                ],
            },
            {
                "name": "enterprise_class",
                "kind": "select",
                "label": "Enterprise class",
                "required": True,
                "options": [
                    {"value": "micro", "label": "Micro"},
                    {"value": "small", "label": "Small"},
                    {"value": "medium", "label": "Medium"},
                ],
            },
            {
                "name": "activity",
                "kind": "select",
                "label": "Activity",
                "required": True,
                "options": [
                    {"value": "manufacturing", "label": "Manufacturing"},
                    {"value": "services", "label": "Services"},
                    {"value": "trading", "label": "Trading"},
                ],
            },
            {
                "name": "nic_code",
                "kind": "text",
                "label": "NIC code (optional)",
                "required": False,
            },
        ],
        "submit_cta": {"label": "Continue", "selection": {"action": "eligibility"}},
    }


def case_carousel() -> dict[str, Any]:
    return {
        "title": "Choose a sample case or continue with your own",
        "subtitle": "Sample files are fictional demo data.",
        "items": [
            {
                "id": "case1_clean",
                "title": "Case 1 — clean match",
                "subtitle": "PO, GRN, and invoice quantities match",
                "badges": [{"label": "Demo", "variant": "info"}],
                "secondary_text": "INR 1,80,000",
                "primary_cta": {
                    "label": "Load",
                    "selection": {"action": "load_case", "case_id": "case1_clean"},
                },
            },
            {
                "id": "case2_po_mismatch",
                "title": "Case 2 — PO mismatch",
                "subtitle": "Invoice qty differs from PO",
                "badges": [{"label": "Mismatch", "variant": "warning"}],
                "secondary_text": "INR 2,40,000",
                "primary_cta": {
                    "label": "Load",
                    "selection": {"action": "load_case", "case_id": "case2_po_mismatch"},
                },
            },
            {
                "id": "case3_no_delivery_proof",
                "title": "Case 3 — no delivery proof",
                "subtitle": "GRN / delivery missing",
                "badges": [{"label": "Blocked reminder", "variant": "warning"}],
                "secondary_text": "INR 95,000",
                "primary_cta": {
                    "label": "Load",
                    "selection": {"action": "load_case", "case_id": "case3_no_delivery_proof"},
                },
            },
            {
                "id": "case_custom_new",
                "title": "New Case — Custom Invoice",
                "subtitle": "Describe any overdue invoice in plain English",
                "badges": [{"label": "AI Intake", "variant": "success"}],
                "secondary_text": "ASI:One Extractor",
                "primary_cta": {
                    "label": "Create",
                    "selection": {"action": "new_case"},
                },
            },
        ],
    }


def readiness_card(result: Any) -> dict[str, Any]:
    return {
        "title": f"Scheme Readiness: {getattr(result, 'scheme', 'Official Scheme')}",
        "subtitle": getattr(result, "label", "Draft checklist, confirm with the lender or official portal"),
        "summary_rows": [
            {"label": "Scheme", "value": getattr(result, "scheme", "Scheme")},
            {"label": "Documents Held", "value": f"{len(getattr(result, 'held', []))} document(s)"},
            {"label": "Documents Missing", "value": f"{len(getattr(result, 'missing', []))} document(s)"},
            {"label": "Official Sources", "value": f"{len(getattr(result, 'sources', []))} verified portal link(s)"},
        ],
        "approve_cta": {
            "label": "Done / Back to Home",
            "selection": {"action": "reset"},
            "primary": True,
        },
    }


def payment_card(invoice_no: str, amount: float, currency: str, recipient: str) -> dict[str, Any]:
    return {
        "title": f"Payment Settlement Request — {invoice_no}",
        "subtitle": "Fetch.ai Agent Payment Protocol (v0.1.0)",
        "summary_rows": [
            {"label": "Invoice", "value": invoice_no},
            {"label": "Settlement Amount", "value": f"{currency} {amount:,.2f}"},
            {"label": "Payee Address", "value": (recipient[:22] + "...") if len(recipient) > 22 else recipient},
            {"label": "Payment Method", "value": "fet_direct / skyfire"},
        ],
        "approve_cta": {
            "label": "Simulate Buyer Settlement",
            "selection": {"action": "simulate_settlement", "invoice_no": invoice_no},
            "primary": True,
        },
        "reject_cta": {"label": "Back to Review", "selection": {"action": "keep_package"}},
    }


def package_review(
    case: CasePackage,
    estimate: InterestEstimate,
    rec: ReconcileResult,
    drafts: list[Draft],
) -> dict[str, Any]:
    rules = load_rules()
    disclaimer_val = rules.get("disclaimer")
    if isinstance(disclaimer_val, dict):
        disclaimer = disclaimer_val.get("value") or DISCLAIMER
    else:
        disclaimer = disclaimer_val or DISCLAIMER

    findings = "; ".join(f.message for f in rec.findings) or "none"
    return {
        "title": "Case package for review",
        "summary_rows": [
            {"label": "Invoice", "value": f"{case.invoice_no} · {case.currency} {case.invoice_amount:.2f}"},
            {"label": "Buyer", "value": case.buyer.name},
            {"label": "Due date", "value": f"{estimate.due_date} ({estimate.label})"},
            {"label": "Overdue days", "value": f"{estimate.overdue_days} ({estimate.label})"},
            {
                "label": "Interest",
                "value": f"{estimate.currency} {estimate.interest:.2f} ({estimate.label})",
            },
            {"label": "Reconcile", "value": f"{rec.mode} · {findings}"},
            {"label": "Drafts", "value": f"{len(drafts)} unsent draft(s)"},
            {"label": "Guardrail", "value": disclaimer},
        ],
        "approve_cta": {
            "label": "Keep package (do not send)",
            "selection": {"action": "keep_package"},
            "primary": True,
        },
        "reject_cta": {"label": "Start over", "selection": {"action": "reset"}},
    }


def package_detail(case: CasePackage, estimate: InterestEstimate, rec: ReconcileResult) -> dict[str, Any]:
    return {
        "title": f"Invoice {case.invoice_no}",
        "summary_rows": [
            {"label": "Supplier", "value": case.supplier.name},
            {"label": "Buyer", "value": case.buyer.name},
            {"label": "PO", "value": case.po_no or "not on file"},
            {"label": "GRN", "value": case.grn_no or "not on file"},
            {"label": "Estimate label", "value": estimate.label},
            {"label": "Match", "value": "yes" if rec.matched else "no"},
        ],
        "actions": [
            {"label": "Back to review", "selection": {"action": "keep_package"}, "primary": True}
        ],
    }
