from __future__ import annotations

import os
import re

import requests

from core.calc import load_rules
from core.models import CasePackage, Draft, InterestEstimate, ReconcileResult


def _forbidden_terms() -> list[str]:
    return [t.lower() for t in load_rules()["forbidden_draft_terms"]]


def draft_violations(text: str) -> list[str]:
    lowered = text.lower()
    return [term for term in _forbidden_terms() if term in lowered]


def sanitize_draft_text(text: str) -> str:
    cleaned = text
    for term in _forbidden_terms():
        cleaned = re.sub(re.escape(term), "[removed]", cleaned, flags=re.IGNORECASE)
    if "not legal advice" not in cleaned.lower():
        cleaned += "\n\nThis draft is for review only. It is not legal advice and has not been sent."
    return cleaned.strip()


def _template_reminder(case: CasePackage, estimate: InterestEstimate, rec: ReconcileResult) -> Draft:
    grn = case.grn_no or case.delivery_date or "not on file"
    findings = "; ".join(f.message for f in rec.findings) or "none noted"
    body = (
        f"Dear {case.buyer.name},\n\n"
        f"This is a factual payment reminder prepared for the supplier's review. "
        f"It is not legal advice and must not be sent until a person reviews it.\n\n"
        f"Invoice {case.invoice_no} dated {case.invoice_date} for {case.currency} "
        f"{case.invoice_amount:.2f} issued by {case.supplier.name} remains unpaid as of {estimate.as_of}.\n"
        f"PO on file: {case.po_no or 'not on file'}. Delivery/GRN on file: {grn}.\n"
        f"Due date used for this working: {estimate.due_date} ({estimate.label}).\n"
        f"Overdue days: {estimate.overdue_days} ({estimate.label}).\n"
        f"Interest working: {case.currency} {estimate.interest:.2f} using RBI bank rate "
        f"{estimate.rbi_bank_rate:.2%} (as of {estimate.rbi_bank_rate_as_of}) × 3, "
        f"compounded monthly ({estimate.label}). Please verify the current notified bank rate.\n"
        f"Document notes: {findings}.\n\n"
        f"Please confirm whether payment has been made or the expected payment date.\n\n"
        f"Regards,\n{case.supplier.name}\n"
        f"Draft for review only. Not sent."
    )
    return Draft(
        kind="reminder",
        subject=f"Payment reminder — invoice {case.invoice_no} (draft for review)",
        body=sanitize_draft_text(body),
    )


def _template_documents(case: CasePackage, rec: ReconcileResult) -> Draft:
    notes = "; ".join(f.message for f in rec.findings) or "supporting documents incomplete"
    body = (
        f"Dear {case.buyer.name},\n\n"
        f"We are preparing an internal overdue-invoice file for invoice {case.invoice_no} "
        f"dated {case.invoice_date}. This note is a draft for review only and is not legal advice.\n\n"
        f"The working file is missing or mismatched on: {notes}.\n"
        f"Please share the purchase order, delivery proof / GRN, and payment status so we can update our records.\n\n"
        f"Regards,\n{case.supplier.name}\n"
        f"Draft for review only. Not sent."
    )
    return Draft(
        kind="document_request",
        subject=f"Document check — invoice {case.invoice_no} (draft for review)",
        body=sanitize_draft_text(body),
    )


def build_drafts(
    case: CasePackage,
    estimate: InterestEstimate,
    rec: ReconcileResult,
) -> list[Draft]:
    if rec.can_draft_payment_reminder:
        follow = Draft(
            kind="followup",
            subject=f"Follow-up — invoice {case.invoice_no} (draft for review)",
            body=sanitize_draft_text(
                _template_reminder(case, estimate, rec).body.replace(
                    "payment reminder", "follow-up on unpaid invoice", 1
                )
            ),
        )
        return [_template_reminder(case, estimate, rec), follow]
    return [_template_documents(case, rec)]


def asi1_complete(user_prompt: str, system_prompt: str) -> str | None:
    api_key = os.getenv("ASI1_API_KEY")
    if not api_key:
        return None
    base = os.getenv("ASI1_BASE_URL", "https://api.asi1.ai/v1").rstrip("/")
    url = base if base.endswith("chat/completions") else f"{base}/chat/completions"
    model = os.getenv("ASI1_MODEL", "asi1-mini")
    try:
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": 800,
            },
            timeout=30,
        )
        response.raise_for_status()
        return str(response.json()["choices"][0]["message"]["content"])
    except (requests.RequestException, KeyError, IndexError, ValueError):
        return None
