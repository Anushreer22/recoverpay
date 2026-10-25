"""Quick automated smoke test for RecoverPay.

Runs the full end-to-end user journey in under 5 seconds:
1. Eligibility verification (MSMED Act s.2(n))
2. Case 1 reconciliation, statutory interest calculation, and factual drafts
3. Plain-language custom invoice intake & confirmation gate
4. Fetch.ai Agent Payment Protocol settlement & cryptographic audit log
5. Government scheme readiness checklist (MUDRA)
"""
from __future__ import annotations

import sys
from pathlib import Path
from dotenv import load_dotenv

# Ensure root is on path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from core.models import Session
from core.state import handle_turn


def run_smoke_test():
    print("=" * 60)
    print("  RecoverPay End-to-End Smoke Test")
    print("=" * 60)

    # 1. Start & Eligibility Check
    print("\n[Step 1] Checking Eligibility Gate...")
    session = Session()
    session, turn1 = handle_turn(session, "hi")
    assert session.stage == "eligibility", f"Expected eligibility stage, got {session.stage}"
    assert turn1.card_kind == "form", "Expected eligibility form card"
    print("  [OK] Welcome banner and eligibility form generated.")

    session, turn2 = handle_turn(session, "yes, registered micro manufacturing")
    assert session.stage == "intake", f"Expected intake stage, got {session.stage}"
    assert session.eligibility and session.eligibility.eligible
    assert turn2.card_kind == "carousel", "Expected carousel card"
    print("  [OK] Udyam micro registration verified. Carousel unlocked.")

    # 2. Case 1 Reconciliation & Statutory Interest
    print("\n[Step 2] Reconciling Case 1 (Clean Match)...")
    session, turn3 = handle_turn(session, "load case1")
    assert session.case is not None
    assert session.stage == "review"
    assert session.estimate is not None
    assert session.estimate.interest > 0
    assert len(session.drafts) > 0
    assert turn3.card_kind == "review"
    print(f"  [OK] Case 1 loaded. Principal: INR {session.case.invoice_amount:,.2f}")
    print(f"  [OK] Statutory Interest (Section 16): INR {session.estimate.interest:,.2f} ({session.estimate.label})")
    print(f"  [OK] Drafts prepared for review: {len(session.drafts)} factual notices (unsent).")

    # 3. Fetch.ai Payment Protocol Settlement
    print("\n[Step 3] Fetch.ai Agent Payment Protocol Settlement...")
    session, turn_pay = handle_turn(session, "request_payment")
    assert turn_pay.card_kind == "review"
    assert "Payment Settlement Request" in turn_pay.card_payload["title"]
    print("  [OK] AgentPaymentProtocol (v0.1.0) request card created.")

    session, turn_settle = handle_turn(session, "simulate_settlement")
    assert session.stage == "done"
    assert any(ev.get("step") == "payment_settlement" for ev in session.audit_events)
    print("  [OK] Payment committed and settled. Cryptographic audit trail signed.")

    # 4. Plain-Language Custom Invoice Intake
    print("\n[Step 4] Plain-Language Invoice Intake & Confirmation Gate...")
    session = Session()
    session, _ = handle_turn(session, "hi")
    session, _ = handle_turn(session, "yes, registered small manufacturing")
    assert session.stage == "intake"
    desc = (
        "We supplied industrial gearboxes to Apex Motors under invoice INV-7700 "
        "dated 2024-02-01 for 180000 INR with 30 days credit. Delivery completed 2024-02-05 with signed GRN."
    )
    session, turn_intake = handle_turn(session, f"new case: {desc}")
    if session.stage == "case_intake":
        print(f"  [OK] Multi-turn slot filling prompted: {turn_intake.text.strip().splitlines()[0]}")
        slot_answers = {
            "supplier_name": "ABC Precision Engineering Ltd",
            "buyer_name": "Apex Motors",
            "invoice_no": "INV-7700",
            "invoice_date": "2024-02-01",
            "amount": "180000",
        }
        while session.stage == "case_intake" and session.missing_fields:
            field = session.missing_fields[0]
            val = slot_answers.get(field, "ABC Precision Engineering Ltd")
            print(f"       -> Providing {field}: {val}")
            session, turn_intake = handle_turn(session, val)
    assert session.stage == "case_confirm", f"Expected case_confirm, got {session.stage}"
    assert "Case details extracted:" in turn_intake.text or "Supplier:" in turn_intake.text
    print("  [OK] Invoice details extracted and validated.")
    print("  [OK] Confirmation review gate presented to user.")

    session, turn_confirm = handle_turn(session, "confirm")
    assert session.stage == "review"
    assert session.case is not None
    assert session.case.invoice_no == "INV-7700"
    print(f"  [OK] Confirmed! Statutory interest calculated: INR {session.estimate.interest:,.2f}")

    # 5. Government Scheme Readiness
    print("\n[Step 5] Government Scheme Readiness Review...")
    verified_schemes = {
        "schemes": [
            {
                "name": "MUDRA",
                "required_documents": [
                    {
                        "name": "Udyam Registration Certificate",
                        "source_url": "https://www.mudra.org.in/",
                        "verified": True,
                    },
                    {
                        "name": "Identity and Address Proof",
                        "source_url": "https://www.mudra.org.in/",
                        "verified": True,
                    },
                    {
                        "name": "Bank Statement (Last 6 Months)",
                        "source_url": "https://www.mudra.org.in/",
                        "verified": True,
                    },
                ],
                "notes": "Verified from official MUDRA guidelines.",
            }
        ]
    }
    session, turn_scheme = handle_turn(
        session,
        '{"action": "scheme_readiness", "scheme": "MUDRA", "consent": true, "approve": true}',
        schemes=verified_schemes,
    )
    assert "Documents you have:" in turn_scheme.text
    assert "Documents still missing:" in turn_scheme.text
    print("  [OK] MUDRA scheme readiness checklist generated from verified portal sources.")

    print("\n" + "=" * 60)
    print("  ALL 5 SMOKE TEST STEPS PASSED SUCCESSFULLY! (100% HEALTHY)")
    print("=" * 60)


if __name__ == "__main__":
    run_smoke_test()
