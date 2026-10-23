# RecoverPay

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

Multi-agent uAgents system for Fetch-A-Thon 3.0. It prepares overdue-invoice case packages for Indian MSME suppliers.

Drafts for review only. Not legal advice. Messages are never auto-sent. No Samadhaan/portal automation.

## Agents

| Name | Role & Discovery Description | Port | Run Command | Seed Env Var |
|---|---|---|---|---|
| **recoverpay-orchestrator** | Coordinates MSME overdue claims across specialist agents. Guides supplier eligibility, credit queries, manages timeouts, retries, and user fallback approval gates. | 8000 | `python -m agents.orchestrator.agent` | `ORCHESTRATOR_SEED` |
| **recoverpay-verifier** | Full evidence verification cross-checking purchase orders, invoices, and delivery proofs (GRN). Drafts for review only; never auto-sends. Supports `FORCE_FAIL=true` recovery testing. | 8001 | `python -m agents.verifier.agent` | `VERIFIER_SEED` |
| **recoverpay-fallback** | Rule-based fallback reconciliation in mode `lite` with fewer checks when evidence is incomplete or verifier times out. Advisory only. | 8002 | `python -m agents.fallback.agent` | `FALLBACK_SEED` |
| **recoverpay-drafter** | Factual overdue-invoice drafting (payment reminders, document check notices, summaries) using ASI1 in the live path with fixed template fallback. | 8003 | `python -m agents.drafter.agent` | `DRAFTER_SEED` |

All four agents implement the **Agent Chat Protocol (ACP)** and can be registered and discovered on Agentverse.

Talk to the orchestrator from ASI:One after connecting its mailbox in the Agentverse inspector.

## Guardrails

- Ask for Udyam / micro-or-small / manufacturing-or-services before any working.
- Every money figure is labelled **estimate, verify**.
- Drafts use factual language only (no threats, no legal conclusions).
- Nothing is sent to a buyer or government portal.

## Setup (Windows)

Python 3.10+ (3.11 preferred). This repo uses a venv at `.venv`.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env            # set seeds and optional ASI1_API_KEY
```

Confirm Agent Chat Protocol 0.3.0:

```bash
python -c "from uagents_core.contrib.protocols.chat import chat_protocol_spec; print(chat_protocol_spec.name, chat_protocol_spec.version)"
```

## Running All Agents Locally

To launch all four agents simultaneously in separate PowerShell windows:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_all.ps1
```

Or run each agent manually in separate terminal windows from the repo root:

```powershell
python -m agents.orchestrator.agent
python -m agents.verifier.agent
python -m agents.fallback.agent
python -m agents.drafter.agent
```

After startup, you can copy each agent's `agent1q...` address into `.env`:
```env
VERIFIER_ADDRESS=agent1q...
FALLBACK_ADDRESS=agent1q...
DRAFTER_ADDRESS=agent1q...
```
*(If left blank, the orchestrator runs the pipeline locally with full typing and guardrails).*

## Failure Recovery Demo (`FORCE_FAIL=true`)

To simulate a verifier timeout and demonstrate automated retry and fallback approval:

1. In PowerShell:
   ```powershell
   $env:FORCE_FAIL="true"
   python -m agents.verifier.agent
   ```
2. When the orchestrator requests verification from `recoverpay-verifier`:
   - Verifier reads `FORCE_FAIL=true` and drops the reply.
   - Orchestrator times out after 5 seconds, retries once.
   - Upon second timeout, marks the step failed, transitions session to `waiting_for_approval`, and prompts the user in chat.
   - Replying `approve` triggers `recoverpay-fallback` (mode `lite`, fewer checks) and resumes from checkpoint without re-running done steps.
   - Replying `refuse` cleanly ends the session.

## Test

```bash
pytest -v
```

## Demo cases

- `case1_clean` — PO, GRN, invoice match
- `case2_po_mismatch` — quantity/amount mismatch
- `case3_no_delivery_proof` — no GRN; document-request draft only
