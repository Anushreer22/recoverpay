# RecoverPay

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

Multi-agent system for Fetch-A-Thon 3.0. It prepares overdue-invoice case packages for Indian MSME suppliers.

Drafts for review only. Not legal advice. Messages are never auto-sent. No Samadhaan/portal automation.

## Agents

| Name | Run | Address |
|---|---|---|
| recoverpay-orchestrator | `python -m agents.orchestrator.agent` | (copy from startup log) |
| recoverpay-reconciler | `python -m agents.reconciler.agent` | (copy from startup log) |
| recoverpay-reconciler-lite | `python -m agents.reconciler_lite.agent` | (copy from startup log) |
| recoverpay-drafter | `python -m agents.drafter.agent` | (copy from startup log) |

Talk to the orchestrator from ASI:One after connecting its mailbox in the Agentverse inspector.

## Guardrails

- Ask for Udyam / micro-or-small / manufacturing-or-services before any working.
- Every money figure is labelled **estimate, verify**.
- Drafts use factual language only (no threats, no legal conclusions).
- Nothing is sent to a buyer or government portal.

## Setup (Windows)

Python 3.10+ (3.12 preferred). This repo uses a venv at `.venv`.

```bash
python -m venv .venv
source .venv/Scripts/activate   # Git Bash
pip install -r requirements.txt
cp .env.example .env            # then set seeds and optional ASI1_API_KEY
```

Confirm Agent Chat Protocol 0.3.0:

```bash
python -c "from uagents_core.contrib.protocols.chat import chat_protocol_spec; print(chat_protocol_spec.name, chat_protocol_spec.version)"
```

## Run

From the repo root, one Git Bash window per agent:

```bash
python -m agents.orchestrator.agent
python -m agents.reconciler.agent
python -m agents.reconciler_lite.agent
python -m agents.drafter.agent
```

Open the inspector URL printed for the orchestrator, Connect → Mailbox, then chat from ASI:One.

After first start, you may paste specialist `agent1q...` addresses into `.env` as `RECONCILER_ADDRESS`, `RECONCILER_LITE_ADDRESS`, and `DRAFTER_ADDRESS`. The user workflow still completes if those are blank: the orchestrator runs the same typed core locally.

## Test

```bash
pytest
```

## Demo cases

- `case1_clean` — PO, GRN, invoice match
- `case2_po_mismatch` — quantity/amount mismatch
- `case3_no_delivery_proof` — no GRN; document-request draft only
