from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from core.models import CasePackage, Party

MONTH_MAP = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

REQUIRED_CASE_FIELDS = [
    "supplier_name",
    "buyer_name",
    "invoice_no",
    "invoice_date",
    "amount",
]

FIELD_LABELS = {
    "supplier_name": "supplier (your business) name",
    "buyer_name": "buyer name",
    "invoice_no": "invoice number",
    "invoice_date": "invoice date (accepts DD-MM-YYYY, DD/MM/YYYY, YYYY-MM-DD, or '5 Sept 2026')",
    "amount": "invoice amount",
    "delivery_date": "delivery date (accepts DD-MM-YYYY, DD/MM/YYYY, YYYY-MM-DD, or '5 Sept 2026')",
    "po_no": "purchase order (PO) number",
    "po_amount": "PO amount",
    "agreed_terms_days": "agreed payment terms in days",
    "payments_received": "payments received",
    "notes": "notes",
}

FIELD_ALIASES = {
    "supplier": "supplier_name",
    "supplier_name": "supplier_name",
    "buyer": "buyer_name",
    "buyer_name": "buyer_name",
    "invoice": "invoice_no",
    "invoice_no": "invoice_no",
    "invoice_number": "invoice_no",
    "inv": "invoice_no",
    "invoice_date": "invoice_date",
    "inv_date": "invoice_date",
    "date": "invoice_date",
    "amount": "amount",
    "invoice_amount": "amount",
    "po": "po_no",
    "po_no": "po_no",
    "po_number": "po_no",
    "po_amount": "po_amount",
    "delivery": "delivery_date",
    "delivery_date": "delivery_date",
    "deliv_date": "delivery_date",
    "terms": "agreed_terms_days",
    "agreed_terms": "agreed_terms_days",
    "credit_days": "agreed_terms_days",
    "payment_terms": "agreed_terms_days",
    "agreed_terms_days": "agreed_terms_days",
    "payment": "payments_received",
    "payments": "payments_received",
    "payments_received": "payments_received",
    "paid": "payments_received",
    "notes": "notes",
    "note": "notes",
}


def parse_user_date(val: Any) -> date | None:
    """Parses date string supporting DD-MM-YYYY, DD/MM/YYYY, YYYY-MM-DD, and '5 Sept 2026'."""
    if isinstance(val, date):
        return val
    if not val or not isinstance(val, str):
        return None
    cleaned = val.strip()

    # YYYY-MM-DD or YYYY/MM/DD
    m = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$", cleaned)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None

    # DD-MM-YYYY or DD/MM/YYYY
    m = re.match(r"^(\d{1,2})[-/](\d{1,2})[-/](\d{4})$", cleaned)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None

    # 5 Sept 2026, 5th September 2026, 05-Sep-2026, etc.
    m = re.match(r"^(\d{1,2})(?:st|nd|rd|th)?[\s\-_]+([A-Za-z]+)[\s\-_]+(\d{4})$", cleaned)
    if m:
        day = int(m.group(1))
        mon_str = m.group(2).lower()
        year = int(m.group(3))
        if mon_str in MONTH_MAP:
            try:
                return date(year, MONTH_MAP[mon_str], day)
            except ValueError:
                return None

    return None


def parse_user_amount(val: Any) -> float | None:
    """Parses amount stripping commas, rupee sign (₹), Rs., INR, spaces, ensuring >= 0."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val) if val >= 0 else None
    if isinstance(val, str):
        cleaned = re.sub(r"[₹,]|(?:rs\.?|inr)", "", val, flags=re.IGNORECASE).strip()
        try:
            amt = float(cleaned)
            return amt if amt >= 0 else None
        except ValueError:
            return None
    return None


def validate_and_normalize_case_data(
    raw_data: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[str]]:
    """Validates extracted invoice JSON.

    Accepts DD-MM-YYYY, DD/MM/YYYY, YYYY-MM-DD, '5 Sept 2026'.
    Strips commas and rupee sign, requires non-negative amounts.
    Requires delivery date not before invoice date.
    Returns (normalized_dict, error_messages).
    """
    errors: list[str] = []
    normalized: dict[str, Any] = {}

    # Copy string/identity fields
    for field in ("supplier_name", "buyer_name", "invoice_no", "po_no", "notes"):
        val = raw_data.get(field)
        normalized[field] = str(val).strip() if val is not None and str(val).strip() else None

    # Currency
    normalized["currency"] = str(raw_data.get("currency") or "INR")

    # Invoice date
    inv_date_raw = raw_data.get("invoice_date")
    parsed_inv_date: date | None = None
    if inv_date_raw is not None and str(inv_date_raw).strip():
        parsed_inv_date = parse_user_date(inv_date_raw)
        if parsed_inv_date is None:
            errors.append(
                f"Invalid date format for invoice date: '{inv_date_raw}'. "
                "Accepted formats: DD-MM-YYYY, DD/MM/YYYY, YYYY-MM-DD, or '5 Sept 2026'."
            )
        else:
            normalized["invoice_date"] = parsed_inv_date.isoformat()
    else:
        normalized["invoice_date"] = None

    # Delivery date
    deliv_date_raw = raw_data.get("delivery_date")
    parsed_deliv_date: date | None = None
    if deliv_date_raw is not None and str(deliv_date_raw).strip():
        parsed_deliv_date = parse_user_date(deliv_date_raw)
        if parsed_deliv_date is None:
            errors.append(
                f"Invalid date format for delivery date: '{deliv_date_raw}'. "
                "Accepted formats: DD-MM-YYYY, DD/MM/YYYY, YYYY-MM-DD, or '5 Sept 2026'."
            )
        else:
            normalized["delivery_date"] = parsed_deliv_date.isoformat()
    else:
        normalized["delivery_date"] = None

    # Check delivery date not before invoice date
    if parsed_inv_date and parsed_deliv_date and parsed_deliv_date < parsed_inv_date:
        errors.append(
            f"Delivery date ({parsed_deliv_date.isoformat()}) cannot be before invoice date ({parsed_inv_date.isoformat()})."
        )

    # Invoice amount
    amt_raw = raw_data.get("amount") if "amount" in raw_data else raw_data.get("invoice_amount")
    if amt_raw is not None and str(amt_raw).strip():
        parsed_amt = parse_user_amount(amt_raw)
        if parsed_amt is None:
            errors.append(
                f"Invalid invoice amount: '{amt_raw}'. Amount must be a non-negative number."
            )
        else:
            normalized["amount"] = parsed_amt
    else:
        normalized["amount"] = None

    # PO amount
    po_amt_raw = raw_data.get("po_amount")
    if po_amt_raw is not None and str(po_amt_raw).strip():
        parsed_po_amt = parse_user_amount(po_amt_raw)
        if parsed_po_amt is None:
            errors.append(
                f"Invalid PO amount: '{po_amt_raw}'. Amount must be a non-negative number."
            )
        else:
            normalized["po_amount"] = parsed_po_amt
    else:
        normalized["po_amount"] = None

    # Agreed terms days
    terms_raw = raw_data.get("agreed_terms_days") or raw_data.get("agreed_credit_days")
    if terms_raw is not None and str(terms_raw).strip():
        try:
            terms_int = int(terms_raw)
            if terms_int < 0:
                errors.append(f"Agreed payment terms cannot be negative: '{terms_raw}'.")
            else:
                normalized["agreed_terms_days"] = terms_int
        except ValueError:
            errors.append(f"Invalid payment terms: '{terms_raw}'. Must be an integer number of days.")
    else:
        normalized["agreed_terms_days"] = None

    # Payments received
    payments_raw = raw_data.get("payments_received")
    if payments_raw is not None and str(payments_raw).strip():
        parsed_payments = parse_user_amount(payments_raw)
        if parsed_payments is None:
            errors.append(
                f"Invalid payments received: '{payments_raw}'. Amount must be a non-negative number."
            )
        else:
            normalized["payments_received"] = parsed_payments
    else:
        normalized["payments_received"] = 0.0

    # Signed delivery proof
    proof_raw = raw_data.get("signed_delivery_proof")
    if proof_raw is not None:
        if isinstance(proof_raw, bool):
            normalized["signed_delivery_proof"] = proof_raw
        elif str(proof_raw).strip().lower() in {"true", "yes", "1"}:
            normalized["signed_delivery_proof"] = True
        elif str(proof_raw).strip().lower() in {"false", "no", "0"}:
            normalized["signed_delivery_proof"] = False
        else:
            normalized["signed_delivery_proof"] = None
    else:
        normalized["signed_delivery_proof"] = None

    # Multiple invoices flag
    mult_raw = raw_data.get("multiple_invoices")
    if mult_raw is True or str(mult_raw).strip().lower() in {"true", "yes", "1"}:
        normalized["multiple_invoices"] = True
    else:
        normalized["multiple_invoices"] = False

    if errors:
        return None, errors
    return normalized, []


def check_overdue_status(
    invoice_date_str: str,
    delivery_date_str: str | None = None,
    agreed_terms_days: int | None = None,
    as_of: date | None = None,
    max_statutory_credit_days: int = 45,
) -> tuple[bool, str, int]:
    """Returns (is_overdue, due_date_str, overdue_days)."""
    as_of = as_of or date.today()
    start = parse_user_date(delivery_date_str) or parse_user_date(invoice_date_str)
    if not start:
        return True, "unknown", 0

    credit = min(int(agreed_terms_days or max_statutory_credit_days), max_statutory_credit_days)
    due = start + timedelta(days=credit)
    overdue_days = (as_of - due).days
    return (overdue_days > 0), due.isoformat(), max(0, overdue_days)


def format_case_summary(data: dict[str, Any], as_of: date | None = None) -> str:
    """Formats human-readable case summary and action prompt before running calculations."""
    lines = ["Case Summary:"]
    lines.append(f"• Supplier: {data.get('supplier_name') or 'Not specified'}")
    lines.append(f"• Buyer: {data.get('buyer_name') or 'Not specified'}")
    lines.append(f"• Invoice No: {data.get('invoice_no') or 'Not specified'}")
    lines.append(f"• Invoice Date: {data.get('invoice_date') or 'Not specified'}")

    amt = data.get("amount")
    amt_str = f"₹{amt:,.2f}" if amt is not None else "Not specified"
    lines.append(f"• Invoice Amount: {amt_str}")

    terms = data.get("agreed_terms_days")
    terms_str = f"{terms} days" if terms is not None else "None specified (defaults to statutory 45 days)"
    lines.append(f"• Agreed Credit Terms: {terms_str}")

    po_no = data.get("po_no")
    lines.append(f"• PO Number: {po_no or 'None on file'}")

    po_amt = data.get("po_amount")
    if po_amt is not None:
        lines.append(f"• PO Amount: ₹{po_amt:,.2f}")

    deliv = data.get("delivery_date")
    lines.append(f"• Delivery Date: {deliv or 'None on file'}")

    proof = data.get("signed_delivery_proof")
    proof_str = "Yes" if proof is True else ("No" if proof is False else "Not specified")
    lines.append(f"• Signed Delivery Proof: {proof_str}")

    payments = float(data.get("payments_received") or 0.0)
    lines.append(f"• Payments Received: ₹{payments:,.2f}")

    notes = data.get("notes")
    if notes:
        lines.append(f"• Notes: {notes}")

    # Edge cases
    extra_notices: list[str] = []

    # 1. Partial payments notice
    if payments > 0 and amt is not None:
        rem_principal = max(0.0, float(amt) - payments)
        extra_notices.append(
            f"ℹ️ Partial payments of ₹{payments:,.2f} recorded. "
            f"Statutory interest is estimated on the remaining principal only (₹{rem_principal:,.2f})."
        )

    # 2. Overdue status notice
    if data.get("invoice_date"):
        is_overdue, due_str, _ = check_overdue_status(
            invoice_date_str=str(data["invoice_date"]),
            delivery_date_str=data.get("delivery_date"),
            agreed_terms_days=data.get("agreed_terms_days"),
            as_of=as_of,
        )
        if not is_overdue:
            extra_notices.append(
                f"⚠️ Notice: Invoice is not overdue yet (payment due date is {due_str}). "
                "Under Section 15 of the MSMED Act, payment is due within agreed terms (or maximum 45 days). "
                "Statutory compound interest applies only after the due date."
            )

    if extra_notices:
        lines.append("")
        lines.extend(extra_notices)

    lines.append("\nPlease reply:")
    lines.append("• 'confirm' to approve details and run dispute calculations")
    lines.append("• 'correct <field> <new_value>' to modify any field (e.g. 'correct amount 95000')")
    lines.append("• 'cancel' to discard this case")

    return "\n".join(lines)


def build_case_from_data(data: dict[str, Any]) -> CasePackage:
    """Builds a CasePackage instance from validated case dictionary."""
    inv_no = str(data.get("invoice_no") or "INV-UNKNOWN")
    case_id = f"case_{re.sub(r'[^a-zA-Z0-9_]', '_', inv_no.lower())}"
    supplier = Party(name=str(data.get("supplier_name") or "Supplier"))
    buyer = Party(name=str(data.get("buyer_name") or "Buyer"))
    amt = float(data.get("amount") or 0.0)
    payments = float(data.get("payments_received") or 0.0)
    po_amt = float(data["po_amount"]) if data.get("po_amount") is not None else None
    terms = int(data.get("agreed_terms_days") or 45)
    deliv = data.get("delivery_date")
    proof = data.get("signed_delivery_proof")
    notes = str(data.get("notes") or "")
    if proof is True and "signed proof" not in notes.lower():
        notes = f"Signed delivery proof on file. {notes}".strip()
    elif proof is False and "no signed proof" not in notes.lower():
        notes = f"No signed delivery proof on file. {notes}".strip()

    return CasePackage(
        case_id=case_id,
        supplier=supplier,
        buyer=buyer,
        invoice_no=inv_no,
        invoice_date=str(data.get("invoice_date")),
        invoice_amount=amt,
        currency=str(data.get("currency") or "INR"),
        po_no=data.get("po_no"),
        po_amount=po_amt,
        delivery_date=deliv,
        agreed_credit_days=terms,
        notes=notes,
        payments_received=payments,
        signed_delivery_proof=proof,
    )

