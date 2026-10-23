from __future__ import annotations

import os
import re
from typing import Any

import requests

from core.guardrails import DRAFT_BANNER, ESTIMATE_LABEL, FORBIDDEN_DRAFT_TERMS
from core.models import CasePackage, Draft, InterestEstimate, ReconcileResult


def _forbidden_terms(rules: dict | None = None) -> list[str]:
    if rules and "forbidden_draft_terms" in rules:
        item = rules["forbidden_draft_terms"]
        if isinstance(item, dict) and item.get("value"):
            return [t.lower() for t in item["value"]]
        if isinstance(item, list):
            return [t.lower() for t in item]
    return [t.lower() for t in FORBIDDEN_DRAFT_TERMS]


def draft_violations(text: str, rules: dict | None = None) -> list[str]:
    lowered = text.lower()
    return [term for term in _forbidden_terms(rules) if term in lowered]


def sanitize_draft_text(text: str, rules: dict | None = None) -> str:
    cleaned = text
    for term in _forbidden_terms(rules):
        cleaned = re.sub(re.escape(term), "[removed]", cleaned, flags=re.IGNORECASE)
    if DRAFT_BANNER not in cleaned:
        cleaned = f"{DRAFT_BANNER}\n\n{cleaned}"
    if not cleaned.strip().endswith(DRAFT_BANNER):
        cleaned += f"\n\n{DRAFT_BANNER}"
    return cleaned.strip()


def _template_reminder(
    case: CasePackage,
    estimate: InterestEstimate,
    rec: ReconcileResult,
    rules: dict | None = None,
) -> Draft:
    grn = case.grn_no or case.delivery_date or "not on file"
    findings = "; ".join(f.message for f in rec.findings) or "none noted"
    mult = (
        round(estimate.annual_rate / estimate.rbi_bank_rate, 2)
        if estimate.rbi_bank_rate
        else 3.0
    )
    body = (
        f"{DRAFT_BANNER}\n\n"
        f"Dear {case.buyer.name},\n\n"
        f"This is a factual payment reminder prepared for the supplier's review. "
        f"{DRAFT_BANNER}\n\n"
        f"Invoice {case.invoice_no} dated {case.invoice_date} for {case.currency} "
        f"{case.invoice_amount:.2f} issued by {case.supplier.name} remains unpaid as of {estimate.as_of}.\n"
        f"PO on file: {case.po_no or 'not on file'}. Delivery/GRN on file: {grn}.\n"
        f"Due date used for this working: {estimate.due_date} ({estimate.label}).\n"
        f"Overdue days: {estimate.overdue_days} ({estimate.label}).\n"
        f"Interest working: {case.currency} {estimate.interest:.2f} using RBI bank rate "
        f"{estimate.rbi_bank_rate:.2%} (as of {estimate.rbi_bank_rate_as_of}) × {mult:g}, "
        f"compounded monthly ({estimate.label}). Please verify the current notified bank rate.\n"
        f"Document notes: {findings}.\n\n"
        f"Please confirm whether payment has been made or the expected payment date.\n\n"
        f"Regards,\n{case.supplier.name}\n\n"
        f"{DRAFT_BANNER}"
    )
    return Draft(
        kind="reminder",
        subject=f"Payment reminder — invoice {case.invoice_no} (draft for review)",
        body=sanitize_draft_text(body, rules),
    )


def _template_documents(case: CasePackage, rec: ReconcileResult, rules: dict | None = None) -> Draft:
    notes = "; ".join(f.message for f in rec.findings) or "supporting documents incomplete"
    body = (
        f"{DRAFT_BANNER}\n\n"
        f"Dear {case.buyer.name},\n\n"
        f"We are preparing an internal overdue-invoice file for invoice {case.invoice_no} "
        f"dated {case.invoice_date}. {DRAFT_BANNER}\n\n"
        f"The working file is missing or mismatched on: {notes}.\n"
        f"Please share the purchase order, delivery proof / GRN, and payment status so we can update our records.\n\n"
        f"Regards,\n{case.supplier.name}\n\n"
        f"{DRAFT_BANNER}"
    )
    return Draft(
        kind="document_request",
        subject=f"Document check — invoice {case.invoice_no} (draft for review)",
        body=sanitize_draft_text(body, rules),
    )


def build_drafts(
    case: CasePackage,
    estimate: InterestEstimate,
    rec: ReconcileResult,
    rules: dict | None = None,
) -> list[Draft]:
    if rec.can_draft_payment_reminder:
        reminder = _template_reminder(case, estimate, rec, rules)
        follow_body = reminder.body.replace("payment reminder", "follow-up on unpaid invoice", 1)
        follow = Draft(
            kind="followup",
            subject=f"Follow-up — invoice {case.invoice_no} (draft for review)",
            body=sanitize_draft_text(follow_body, rules),
        )
        return [reminder, follow]
    return [_template_documents(case, rec, rules)]


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
