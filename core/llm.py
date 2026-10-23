from __future__ import annotations

import json
import os
import re
from typing import Any

import requests

from core.guardrails import DRAFT_BANNER, ESTIMATE_LABEL, FORBIDDEN_DRAFT_TERMS
from core.models import (
    CasePackage,
    Draft,
    Finding,
    InterestEstimate,
    ReconcileResult,
    case_from_dict,
)


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


def build_drafts_template(
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
    api_key = os.getenv("ASI1_API_KEY") or os.getenv("ASI_ONE_API_KEY")
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


def parse_case_with_asi1(text: str) -> tuple[CasePackage | None, bool]:
    """
    (a) Turn user's free text into a CasePackage using ASI1.
    Returns (case, used_asi1). If ASI1 is unavailable or fails, returns (None, False).
    """
    if not (os.getenv("ASI1_API_KEY") or os.getenv("ASI_ONE_API_KEY")):
        return None, False

    sys_prompt = (
        "You are an MSME data extraction engine. Extract invoice details from user text into strict JSON "
        "matching this structure:\n"
        "{\n"
        '  "case_id": "case_custom",\n'
        '  "supplier": {"name": "Supplier Name", "gstin": null, "state": null, "udyam": null},\n'
        '  "buyer": {"name": "Buyer Name", "gstin": null, "state": null},\n'
        '  "invoice_no": "INV-100",\n'
        '  "invoice_date": "2024-01-01",\n'
        '  "invoice_amount": 100000.0,\n'
        '  "currency": "INR",\n'
        '  "po_no": null,\n'
        '  "agreed_credit_days": 45,\n'
        '  "line_items": []\n'
        "}\n"
        "Output ONLY raw JSON. No explanations, no markdown fences."
    )
    raw = asi1_complete(user_prompt=text, system_prompt=sys_prompt)
    if not raw:
        return None, False
    try:
        clean_raw = raw.strip()
        if clean_raw.startswith("```"):
            clean_raw = re.sub(r"^```[a-zA-Z]*\n?", "", clean_raw)
            clean_raw = re.sub(r"\n?```$", "", clean_raw).strip()
        data = json.loads(clean_raw)
        return case_from_dict(data), True
    except Exception:
        return None, False


def explain_evidence_gaps(findings: list[Finding], case: CasePackage) -> tuple[str, bool]:
    """
    (b) Explain evidence gaps in plain language using ASI1.
    Returns (explanation, used_asi1). If ASI1 fails, falls back to factual template text.
    """
    if not findings:
        return "No evidence gaps identified. Supporting documents appear complete.", False

    findings_text = "; ".join(f.message for f in findings)
    if not (os.getenv("ASI1_API_KEY") or os.getenv("ASI_ONE_API_KEY")):
        return f"Evidence gaps noted (template fallback): {findings_text}", False

    sys_prompt = (
        "You are a factual MSME documentation specialist. Explain the following invoice document findings "
        "and evidence gaps in simple, neutral plain language for an Indian MSME supplier. "
        "Do NOT make legal threats, do NOT promise recovery, do NOT cite legal conclusions. "
        "Keep it strictly factual and objective."
    )
    user_prompt = f"Case {case.invoice_no} findings: {findings_text}."
    explained = asi1_complete(user_prompt=user_prompt, system_prompt=sys_prompt)
    if explained and not draft_violations(explained):
        return explained.strip(), True
    return f"Evidence gaps noted (template fallback): {findings_text}", False


def build_drafts_with_status(
    case: CasePackage,
    estimate: InterestEstimate,
    rec: ReconcileResult,
    rules: dict | None = None,
    use_llm: bool = True,
) -> tuple[list[Draft], bool]:
    """
    (c) Word drafts inside fixed templates using ASI1.
    If ASI1 fails, falls back to fixed templates and sets used_asi1=False.
    """
    base_drafts = build_drafts_template(case, estimate, rec, rules)
    if not use_llm or not (os.getenv("ASI1_API_KEY") or os.getenv("ASI_ONE_API_KEY")):
        return base_drafts, False

    if not rec.can_draft_payment_reminder:
        # When delivery proof or evidence is incomplete, payment reminders are blocked
        return base_drafts, False

    try:
        findings = "; ".join(f.message for f in rec.findings) or "none noted"
        sys_prompt = (
            f"You are a factual MSME documentation assistant. Wording must remain strictly inside this banner:\n"
            f"{DRAFT_BANNER}\n\n"
            f"Draft a neutral, polite, factual payment reminder for review by the supplier. "
            f"Mandatory facts: Invoice {case.invoice_no}, Date {case.invoice_date}, Amount {case.currency} {case.invoice_amount:.2f}, "
            f"Due date {estimate.due_date} ({estimate.label}), Overdue days {estimate.overdue_days} ({estimate.label}), "
            f"Interest working {case.currency} {estimate.interest:.2f} ({estimate.label}), "
            f"Document notes: {findings}. "
            f"Never threaten legal action. Never conclude guilt. "
            f"End strictly with: {DRAFT_BANNER}"
        )
        user_prompt = f"Draft payment reminder for buyer {case.buyer.name} from supplier {case.supplier.name}."
        llm_body = asi1_complete(user_prompt=user_prompt, system_prompt=sys_prompt)
        if llm_body and not draft_violations(llm_body, rules):
            sanitized = sanitize_draft_text(llm_body, rules)
            reminder = Draft(
                kind="reminder",
                subject=f"Payment reminder — invoice {case.invoice_no} (draft for review)",
                body=sanitized,
            )
            follow_body = sanitized.replace("payment reminder", "follow-up on unpaid invoice", 1)
            follow = Draft(
                kind="followup",
                subject=f"Follow-up — invoice {case.invoice_no} (draft for review)",
                body=sanitize_draft_text(follow_body, rules),
            )
            return [reminder, follow], True
    except Exception:
        pass

    return base_drafts, False


def build_drafts(
    case: CasePackage,
    estimate: InterestEstimate,
    rec: ReconcileResult,
    rules: dict | None = None,
) -> list[Draft]:
    drafts, _ = build_drafts_with_status(case, estimate, rec, rules, use_llm=True)
    return drafts
