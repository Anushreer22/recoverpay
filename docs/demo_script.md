# RecoverPay Demo Script (Fetch-A-Thon 3.0 / ASI:One)

> **Mandatory Disclaimer**: Nothing in this demo is legal advice. All calculations are estimates for verification. Drafts are for internal review only and are **never** auto-sent to buyers or filed on Samadhaan.

---

## Architecture Overview

RecoverPay is an asynchronous multi-agent system built on the **Fetch.ai uAgents framework** and the **Agent Chat Protocol (ACP 0.3.0)**:

1. **`recoverpay-orchestrator` (Port 8000)**: Coordinates workflow, manages timeouts, prompts for human approval, and maintains the append-only audit trail.
2. **`recoverpay-verifier` (Port 8001)**: Full evidence cross-matching (PO, invoice, GRN). Supports simulated outage via `FORCE_FAIL=true`.
3. **`recoverpay-fallback` (Port 8002)**: Fast rule-based reconciliation in mode `lite` with fewer checks when evidence is incomplete or verifier is offline.
4. **`recoverpay-drafter` (Port 8003)**: Factual drafting engine using **ASI:One (`asi1-mini`)** in the live path with fixed template fallback.

---

## Pre-Demo Setup

1. Start all 4 agents in separate PowerShell windows:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\run_all.ps1
   ```
2. Open **[ASI:One Chat](https://asi1.ai/chat)** (or the Agentverse Inspector) and open your chat with `recoverpay-orchestrator`.

---

## Stage 1: The MSME Eligibility Gate

Show the judges that RecoverPay strictly complies with the MSMED Act 2006 statutory scope before processing any claims.

1. **Send**:
   ```text
   hi
   ```
   **What to show**: The orchestrator presents the welcome banner and requires confirmation of supplier registration and enterprise size.
2. **Try loading a case early**:
   ```text
   load case1
   ```
   **What to show**: The agent rejects the command: *"Confirm supplier registration and eligibility before loading a case."*
3. **Confirm registration**:
   ```text
   registered micro manufacturing
   ```
   **What to show**: Supplier profile is approved, eligibility audit event is recorded, and the case carousel is unlocked.

---

## Stage 2: Case 1 — Clean Match & Statutory Interest

Demonstrates full evidence reconciliation and interest calculation under Section 16 of the MSMED Act.

1. **Send**:
   ```text
   load case1
   ```
2. **What to show the judges**:
   - **Verification**: Verifier confirms 100% match across PO, invoice, and GRN.
   - **Statutory Interest Working**:
     - Notified RBI Bank Rate: `5.75%` (as of Oct 16, 2026).
     - Statutory Multiplier: `× 3` = `17.25%` per annum.
     - Compounded monthly with 45-day statutory credit cap.
     - Every number is explicitly labeled `Estimate, verify before use`.
   - **Drafts for Review**:
     - Payment reminder and follow-up letter worded factually by ASI:One.
     - Wrapped in `DRAFT FOR REVIEW. Not legal advice.` banners.
3. **Finalize**:
   ```text
   keep_package
   ```
   - Records draft review approval event in audit log. No emails sent.

---

## Stage 3: Case 2 — Discrepancy Detection & Plain English Explanation

Demonstrates how ASI:One explains PO and invoice mismatches without legal threats.

1. **Send**:
   ```text
   reset
   ```
2. **Send**:
   ```text
   registered micro manufacturing
   ```
3. **Send**:
   ```text
   load case2
   ```
4. **What to show the judges**:
   - The verifier detects that PO amount (₹180,000) does not match invoice (₹240,000) and quantity is 4 units vs PO 3 units.
   - ASI:One translates the findings into neutral, objective language for the supplier.
   - Draft notes the discrepancy so the supplier can resolve it before approaching the buyer.

---

## Stage 4: Case 3 — Missing Delivery Proof Blocks Payment Claim

Demonstrates legal safety guardrails under *Silpi Industries v. KSRTC (Supreme Court)*.

1. **Send**:
   ```text
   reset
   ```
2. **Send**:
   ```text
   registered small services
   ```
3. **Send**:
   ```text
   load case3
   ```
4. **What to show the judges**:
   - `grn_no` is null (no delivery proof on file).
   - `Payment-reminder draft allowed: False`.
   - The system **blocks** payment reminders and instead generates a **Document Check Request** asking the buyer to share the GRN/acceptance status.

---

## Stage 5: Live Path ASI:One Free-Text Extraction

Demonstrates LLM structured extraction from messy supplier messages.

1. **Send**:
   ```text
   reset
   ```
2. **Send**:
   ```text
   registered micro manufacturing
   ```
3. **Send**:
   ```text
   We supplied custom brackets to Apex Motors on invoice INV-9900 dated 2024-03-01 for 250000 INR with 30 days credit terms. Delivery was completed on 2024-03-05.
   ```
4. **What to show the judges**:
   - ASI:One extracts buyer, invoice number, amount, and dates on the fly.
   - Immediately calculates interest and drafts factual review notices.

---

## Stage 6: Multi-Agent Failure Recovery Demo (`FORCE_FAIL=true`)

Demonstrates resilience when an agent becomes unresponsive.

1. In the **Verifier** terminal window, press `Ctrl + C` and restart with:
   ```powershell
   $env:FORCE_FAIL="true"
   python -m agents.verifier.agent
   ```
2. In ASI:One chat, send:
   ```text
   reset
   ```
3. Send:
   ```text
   registered micro manufacturing
   ```
4. Send:
   ```text
   load case1
   ```
5. **What happens**:
   - Verifier reads `FORCE_FAIL=true` and drops the request.
   - Orchestrator waits 5 seconds, retries once.
   - Second timeout triggers the human-in-the-loop approval gate:
     > *"Verifier component timed out after 1 retry. The step has failed. A rule-based fallback agent (mode 'lite') can take over with fewer checks. Do you approve running the fallback? Reply 'approve' to proceed, or 'refuse' to cancel."*
6. Send:
   ```text
   approve
   ```
7. **What to show the judges**:
   - Orchestrator records approval in the audit log.
   - `recoverpay-fallback` executes lite reconciliation with fewer checks.
   - Pipeline resumes from checkpoint without re-running completed steps.

---

## Stage 7: Official Scheme Readiness Check

Demonstrates credit and loan scheme checklist preparation.

1. In chat, ask:
   ```text
   I need a credit loan under government schemes
   ```
2. Orchestrator recommends official schemes (MUDRA, PMEGP, Stand-Up India, CGTMSE) and explains that explicit user consent is mandatory.
3. Send:
   ```text
   {"action": "scheme_readiness", "scheme": "MUDRA", "consent": true, "approve": true}
   ```
4. **What to show the judges**:
   - Sourced document checklist with exact portal URLs.
   - Labeled `Draft checklist, confirm with the lender or official portal`.
   - Never outputs speculative words like "eligible", "approved", or "guaranteed".
   - Collects zero sensitive demographic data.
