# RecoverPay 🛡️

[![Fetch.ai](https://img.shields.io/badge/Fetch.ai-uAgents_v0.26-blue.svg)](https://fetch.ai)
[![Innovation Lab](https://img.shields.io/badge/Innovation_Lab-Fetch--A--Thon_3.0-3D8BD3.svg)](https://innovationlab.fetch.ai)
[![ASI:One](https://img.shields.io/badge/ASI:One-asi1--mini-5F43F1.svg)](https://asi1.ai)
[![Python](https://img.shields.io/badge/Python-3.11+-brightgreen.svg)](https://python.org)
[![Tests](https://img.shields.io/badge/Tests-43_Passed-success.svg)](./docs/test_results.md)
[![Agent Chat Protocol](https://img.shields.io/badge/ACP-0.3.0-orange.svg)](https://agentverse.ai)

> **Autonomous Multi-Agent Dispute Reconciliation & Overdue Claim Preparation for Indian Micro, Small, and Medium Enterprises (MSMEs)**  
> Built strictly under the statutory framework of the **Micro, Small and Medium Enterprises Development (MSMED) Act, 2006**.

---

## 📌 Executive Summary

Over ₹10.7 lakh crore remains locked in delayed commercial payments to Indian MSMEs. While Chapter V of the MSMED Act 2006 provides strong legal remedies—including statutory compound interest at **3× the RBI notified bank rate**—suppliers face massive friction:
- Disorganized paper trails (mismatched purchase orders, missing delivery proofs).
- Fear of aggressive legal language damaging long-term buyer relationships.
- Opaque, time-consuming statutory calculations and formal portal procedures.

**RecoverPay** solves this by deploying a collaborative team of autonomous **Fetch.ai uAgents** registered on **Agentverse** and accessible via **ASI:One**. RecoverPay cross-verifies supply evidence, calculates legally compliant compound interest, and prepares objective, factual communication packages for supplier review.

> ⚖️ **Core Legal Guardrail**: RecoverPay prepares draft working files for internal review only. It is **not legal advice**. Drafts are **never auto-sent** to buyers, and **no automated filings** are made to government portals (Samadhaan).

---

## 🏛️ System Architecture

RecoverPay coordinates four specialized microservice agents communicating via typed **uAgents Models** and the **Agent Chat Protocol (ACP 0.3.0)**:

```
                      ┌─────────────────────────────────────────┐
                      │            Supplier / User              │
                      │    (ASI:One Chat / Agentverse UI)       │
                      └────────────────────┬────────────────────┘
                                           │  Agent Chat Protocol
                                           ▼
                      ┌─────────────────────────────────────────┐
                      │         recoverpay-orchestrator         │
                      │               (Port 8000)               │
                      │  - Eligibility Gate & Workflow State    │
                      │  - Timeout Detection & 1-Retry Monitor  │
                      │  - Human-in-the-Loop Fallback Gate      │
                      │  - Append-Only Audit Trail & Checkpoint │
                      └───────┬────────────────────┬────────────┘
                              │                    │
              ReconcileRequest│                    │DraftRequest
                              ▼                    ▼
     ┌────────────────────────────────┐    ┌────────────────────────────────┐
     │      recoverpay-verifier       │    │       recoverpay-drafter       │
     │          (Port 8001)           │    │          (Port 8003)           │
     │  - PO / GRN / Invoice 3-Way    │    │  - ASI:One (asi1-mini) Engine  │
     │  - Mismatch & Gap Flagging     │    │  - Statutory Banner Injection  │
     │  - Simulates Outage via        │    │  - Factual Reminder & Notice   │
     │    FORCE_FAIL=true             │    │  - Guardrail Tone Stripping    │
     └────────────────┬───────────────┘    └────────────────────────────────┘
                      │
        (On Timeout / │ User Approves)
                      ▼
     ┌────────────────────────────────┐
     │      recoverpay-fallback       │
     │          (Port 8002)           │
     │  - Fast Rule-Based "Lite" Mode │
     │  - Fewer Checks for Resilience │
     │  - Resumes without Re-run      │
     └────────────────────────────────┘
```

---

## 🤖 The Specialist Agents

| Agent Name | Role | Port | Seed Environment Variable | Agentverse Discovery Description |
|---|---|---|---|---|
| **`recoverpay-orchestrator`** | Master Workflow Coordinator | `8000` | `ORCHESTRATOR_SEED` | Coordinates MSME overdue claims across specialist agents. Guides supplier eligibility, credit queries, manages timeouts, retries, and user fallback approval gates. |
| **`recoverpay-verifier`** | Evidence Cross-Matching | `8001` | `VERIFIER_SEED` | Full evidence verification cross-checking purchase orders, invoices, and delivery proofs (GRN). Drafts for review only; never auto-sends. Supports `FORCE_FAIL=true` recovery testing. |
| **`recoverpay-fallback`** | Resilient Rule-Based Reconciler | `8002` | `FALLBACK_SEED` | Rule-based fallback reconciliation in mode `lite` with fewer checks when evidence is incomplete or verifier times out. Advisory only. |
| **`recoverpay-drafter`** | Factual Drafting Engine | `8003` | `DRAFTER_SEED` | Factual overdue-invoice drafting (payment reminders, document check notices, summaries) using ASI1 in the live path with fixed template fallback. |

---

## 🛡️ Statutory Guardrails & Legal Integrity

RecoverPay enforces strict compliance with Indian commercial law and judicial precedents:

1. **Eligibility Gate First**: Before calculations or case ingestion, the system validates Udyam registration, micro/small classification, and manufacturing/services activity under Section 2(n).
2. **Statutory Credit Cap**: Pursuant to Section 15, payment terms agreed in excess of 45 days are capped at **45 days** from delivery/acceptance.
3. **Compound Interest Working**: Implements Section 16 penal interest at **3× the notified RBI bank rate**, compounded monthly. Every figure is watermarked with the mandatory label: `Estimate, verify before use`.
4. **Supreme Court Delivery Guardrail (*Silpi Industries*)**: If delivery proof (GRN) is missing, the system **strictly blocks** overdue payment claims and issues an objective document request instead.
5. **Neutral, Non-Aggressive Language**: Aggressive legal threats (`we will sue`, `liable`, `defaulter list`) are automatically sanitized. All drafts carry the header/footer banner: `DRAFT FOR REVIEW. Not legal advice.`
6. **Zero-Auto-Send Security**: Verified by AST static analysis—no unauthorized external transmission code (`smtplib`, non-ASI endpoints) exists in the repository.

---

## 🚀 Quick Start Guide

### 1. Prerequisites
- Python 3.10 or 3.11 (3.11 recommended)
- PowerShell (Windows) or Bash (macOS/Linux)
- Git

### 2. Installation
```powershell
# Clone the repository
git clone https://github.com/Anushreer22/recoverpay.git
cd recoverpay

# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
Copy-Item .env.example .env
```

### 3. Configure `.env`
Edit `.env` to set your unique random recovery seeds and optional API keys:
```env
ASI1_API_KEY=your_asi1_api_key_here
ASI1_BASE_URL=https://api.asi1.ai/v1
ASI1_MODEL=asi1-mini

ORCHESTRATOR_SEED=your-unique-long-orchestrator-seed-phrase
VERIFIER_SEED=your-unique-verifier-seed-phrase
FALLBACK_SEED=your-unique-fallback-seed-phrase
DRAFTER_SEED=your-unique-drafter-seed-phrase
```

---

## 🏃 Running the Multi-Agent System

### Option A: One-Click Launcher (Recommended for Windows)
Starts all four uAgents in separate, titled PowerShell windows:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_all.ps1
```

### Option B: Manual Startup
Open four separate terminal windows and run:
```powershell
# Window 1: Orchestrator (Port 8000)
python -m agents.orchestrator.agent

# Window 2: Verifier (Port 8001)
python -m agents.verifier.agent

# Window 3: Fallback (Port 8002)
python -m agents.fallback.agent

# Window 4: Drafter (Port 8003)
python -m agents.drafter.agent
```

---

## 💬 Interactive Demo Walkthrough

Connect to `recoverpay-orchestrator` via **[ASI:One Chat](https://asi1.ai/chat)** or the local **Agentverse Inspector**:

### Stage 1: Eligibility Assessment
```text
User: hi
Orchestrator: RecoverPay prepares overdue-invoice case packages for Indian MSME suppliers.
              Before any calculation or draft, confirm supplier registration and eligibility.

User: registered micro manufacturing
Orchestrator: Eligibility recorded for this working file. Choose a demo case or send case JSON.
```

### Stage 2: Case 1 — Clean Match & Statutory Calculation
```text
User: load case1
Orchestrator: Working file ready (drafts unsent).
              Interest INR 9,028.89 — Estimate, verify before use.
              Reconcile mode: full. Payment-reminder draft allowed: True.

              [reminder] Payment reminder — invoice INV-2026-118 (draft for review)
              DRAFT FOR REVIEW. Not legal advice.
              Dear Nexus Components Ltd,
              Invoice INV-2026-118 for INR 180,000.00 remains unpaid...
              Interest working: INR 9,028.89 using RBI bank rate 5.75% × 3...
```

### Stage 3: Case 2 — Discrepancy Flagging
```text
User: reset
User: registered micro manufacturing
User: load case2
Orchestrator: Evidence check: PO amount 180000 does not match invoice amount 240000;
              SKU DIE-08: invoice qty 4 vs PO qty 3.
              Draft notes discrepancies so parties can reconcile records objectively.
```

### Stage 4: Case 3 — Missing Delivery Proof Guardrail
```text
User: reset
User: registered small services
User: load case3
Orchestrator: Payment-reminder draft allowed: False.
              [document_request] Document check — invoice INV-SVC-77 (draft for review)
              The working file is missing delivery proof / GRN. Please share records...
```

### Stage 5: Free-Form Text Extraction via ASI:One
Paste raw invoice details directly into the chat:
```text
User: We supplied machined flanges to Bharat Heavy Electricals on invoice INV-7711 dated 2024-02-01 for 500000 INR with 30 days credit. Delivery accepted 2024-02-05.
Orchestrator: Case extracted from text. Working file ready (drafts unsent)...
```

---

## ⚡ Failure Recovery Demo (`FORCE_FAIL=true`)

RecoverPay features robust agent-to-agent fault recovery with human-in-the-loop approval:

1. Stop the **Verifier** agent (`Ctrl + C`) and restart it in forced failure mode:
   ```powershell
   $env:FORCE_FAIL="true"
   python -m agents.verifier.agent
   ```
2. In chat, load a case:
   ```text
   load case1
   ```
3. **Automated Recovery Cycle**:
   - `recoverpay-verifier` drops incoming requests when `FORCE_FAIL=true`.
   - The Orchestrator's `on_interval` monitor detects the missing response and **retries once**.
   - Upon second timeout, the step is marked failed, and the orchestrator requests approval:
     > *"Verifier component timed out after 1 retry. The step has failed. A rule-based fallback agent (mode 'lite') can take over with fewer checks. Do you approve running the fallback? Reply 'approve' to proceed, or 'refuse' to cancel."*
4. Type **`approve`**:
   - Orchestrator records the user approval event.
   - `recoverpay-fallback` executes lite reconciliation with fewer checks.
   - Resumes execution from the checkpoint without re-running completed steps.

---

## 📋 Scheme Readiness Checklists

Suppliers querying credit options or working capital loans can review document readiness for official government schemes:

```text
User: I need a loan under government schemes
Orchestrator: Recommended next steps:
              1. Check MSME delayed payment status
              2. Review scheme readiness checklist (MUDRA, PMEGP, Stand-Up India, CGTMSE)
              Draft checklist, confirm with the lender or official portal.
              Explicit user consent is mandatory.

User: {"action": "scheme_readiness", "scheme": "MUDRA", "consent": true, "approve": true}
Orchestrator: Draft checklist, confirm with the lender or official portal.
              Held: PAN, Udyam Registration
              Missing: 12-month bank statement, ITR returns (with exact portal URLs)
```

---

## 🧪 Comprehensive Verification Suite

Run the full pytest suite (offline, no external network calls required):

```powershell
pytest -v
```

```text
============================= test session starts =============================
collected 43 items

tests/test_calc.py::test_estimate_label_always_present PASSED            [  2%]
tests/test_calc.py::test_not_overdue_is_zero PASSED                      [  4%]
tests/test_calc.py::test_credit_days_capped_at_45 PASSED                 [  6%]
tests/test_calc.py::test_compound_interest_is_positive_when_overdue PASSED [  9%]
tests/test_calc.py::test_eligibility_micro_manufacturing PASSED          [ 11%]
tests/test_calc.py::test_real_rules_calc_raises_rules_not_verified PASSED [ 13%]
tests/test_calc.py::test_real_rules_eligibility_raises_rules_not_verified PASSED [ 16%]
tests/test_calc.py::test_guardrails_estimate_and_draft_exact_banners PASSED [ 18%]
tests/test_failures.py::test_medium_enterprise_blocked PASSED            [ 20%]
tests/test_failures.py::test_unregistered_blocked PASSED                 [ 23%]
tests/test_failures.py::test_trading_blocked PASSED                      [ 25%]
tests/test_failures.py::test_po_mismatch_flagged PASSED                  [ 27%]
tests/test_failures.py::test_no_delivery_proof_blocks_payment_reminder PASSED [ 30%]
tests/test_failures.py::test_forbidden_legal_language_is_stripped PASSED [ 32%]
tests/test_failures.py::test_happy_path_drafts_are_factual PASSED        [ 34%]
tests/test_readiness.py::test_consent_required PASSED                    [ 37%]
tests/test_readiness.py::test_real_unfilled_file_is_rejected PASSED      [ 39%]
tests/test_readiness.py::test_unknown_scheme_rejected PASSED             [ 41%]
tests/test_readiness.py::test_unverified_document_rejected PASSED        [ 44%]
tests/test_readiness.py::test_held_and_missing_lists PASSED              [ 46%]
tests/test_readiness.py::test_label_present_and_no_forbidden_words PASSED [ 48%]
tests/test_readiness.py::test_forbidden_word_in_source_data_is_blocked PASSED [ 51%]
tests/test_readiness.py::test_no_sensitive_fields_in_profile PASSED      [ 53%]
tests/test_recovery.py::test_timeout_then_retry_then_fail PASSED         [ 55%]
tests/test_recovery.py::test_swap_approved_resumes_without_rerunning_done_steps PASSED [ 58%]
tests/test_recovery.py::test_swap_refused_ends_safely PASSED             [ 60%]
tests/test_recovery.py::test_restart_mid_workflow_then_resume PASSED     [ 62%]
tests/test_recovery.py::test_duplicate_message_delivery_does_not_rerun_or_duplicate_audit PASSED [ 65%]
tests/test_recovery.py::test_fallback_result_carries_note_of_fewer_checks PASSED [ 67%]
tests/test_recovery.py::test_approval_gate_finalizing_draft PASSED       [ 69%]
tests/test_recovery.py::test_audit_trail_rendering_and_no_secrets PASSED [ 72%]
tests/test_recovery.py::test_no_external_sending_or_filing_code PASSED   [ 74%]
tests/test_recovery.py::test_verifier_agent_force_fail_never_replies PASSED [ 76%]
tests/test_recovery.py::test_verifier_agent_normal_replies_with_result PASSED [ 79%]
tests/test_recovery.py::test_fallback_agent_replies_with_fewer_checks PASSED [ 81%]
tests/test_recovery.py::test_drafter_agent_replies_with_draft_response PASSED [ 83%]
tests/test_recovery.py::test_orchestrator_timeout_and_retry_on_interval PASSED [ 86%]
tests/test_recovery.py::test_orchestrator_duplicate_reconcile_response_idempotency PASSED [ 88%]
tests/test_recovery.py::test_asi1_live_path_fallback_behavior PASSED     [ 90%]
tests/test_state_machine.py::test_eligibility_is_asked_first PASSED      [ 93%]
tests/test_state_machine.py::test_cannot_load_case_before_eligibility PASSED [ 95%]
tests/test_state_machine.py::test_registered_micro_then_case1 PASSED     [ 97%]
tests/test_state_machine.py::test_keep_package_does_not_send PASSED      [100%]

======================= 43 passed, 1 warning in 19.80s ========================
```

---

## 📁 Repository Structure

```text
recoverpay/
├── agents/                      # uAgents microservices
│   ├── orchestrator/agent.py    # Main workflow & timeout manager
│   ├── verifier/agent.py        # Full evidence cross-checking agent
│   ├── fallback/agent.py        # Rule-based lite fallback agent
│   └── drafter/agent.py         # ASI:One draft preparation agent
├── core/                        # Core business logic & models
│   ├── acp.py                   # Agent Chat Protocol 0.3.0 adapter
│   ├── audit.py                 # Append-only audit logger (secrets redacted)
│   ├── bootstrap.py             # Agent initialization & environment helper
│   ├── calc.py                  # Statutory calculation engine (Section 15 & 16)
│   ├── cards.py                 # Interactive JSON card schemas
│   ├── guardrails.py            # Mandated banners, disclaimers, & tone rules
│   ├── llm.py                   # ASI:One client with template fallbacks
│   ├── messages.py              # Typed uAgents request/response Models
│   ├── models.py                # Dataclasses & serialization logic
│   ├── planner.py               # Recommended steps & scheme discovery
│   ├── readiness.py             # Official credit scheme checklists
│   └── recovery.py              # Timeout handling, step keys, & retry logic
├── data/                        # Verified statutory rules & demo cases
│   ├── cases/                   # Demo cases (clean, mismatch, missing proof)
│   ├── rules.json               # Sourced MSMED legal parameters & citations
│   └── schemes.json             # Official government scheme guidelines
├── docs/                        # Project documentation & presentation guides
│   ├── demo_script.md           # Turn-by-turn pitch & judge demo script
│   └── test_results.md          # Full test suite execution report
├── scripts/
│   └── run_all.ps1              # One-click multi-window agent launcher
├── tests/                       # Comprehensive pytest suite (43 tests)
├── .env.example                 # Template for environment variables
└── README.md                    # Project documentation
```

---

## 📜 Legal Disclaimer

RecoverPay is an educational and workflow automation tool submitted for **Fetch-A-Thon 3.0**. All statutory interest computations, eligibility criteria, and notice drafts are intended exclusively for supplier review prior to taking independent legal or financial counsel. RecoverPay is not affiliated with the Ministry of Micro, Small and Medium Enterprises or the Reserve Bank of India.
