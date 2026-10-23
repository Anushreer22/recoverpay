# Test Results

**Command**: `pytest -v`  
**Result**: 43 passed, 1 warning (asyncio loop deprecation warning) in ~20s  

### Coverage Highlights

1. **Statutory Calculation & Guardrails (`tests/test_calc.py`)**:
   - `ESTIMATE_LABEL` ("Estimate, verify before use") and `DRAFT_BANNER` ("DRAFT FOR REVIEW. Not legal advice.") present on all figures and drafts.
   - MSMED Act Section 15: credit days capped at 45.
   - Non-overdue invoices calculate zero interest.
   - Monthly compound interest at RBI bank rate × 3 multiplier.
   - Real `rules.json` verification validation.

2. **Negative Tests & Boundaries (`tests/test_failures.py`)**:
   - Medium enterprise blocked.
   - Unregistered supplier blocked.
   - Trading activity blocked under Chapter V delayed payment rules.
   - Purchase order quantity & amount discrepancies flagged.
   - Incomplete evidence (missing GRN / delivery proof) strictly blocks payment reminders and allows only document check requests.
   - Aggressive legal/threat terms stripped and sanitized.

3. **Scheme Readiness Checklists (`tests/test_readiness.py`)**:
   - Explicit user consent gate (`ConsentRequired`).
   - Official schemes (MUDRA, PMEGP, Stand-Up India, CGTMSE).
   - Strict unverified document rejection (`SchemeRulesNotVerified`).
   - Sourced document checklists with mandatory draft notice label.
   - Zero sensitive attributes (no gender, caste, religion, or region fields in profile model).
   - Forbidden words strictly blocked from output.

4. **Failure Recovery & State Machine (`tests/test_recovery.py`)**:
   - Timeout detection after 1 retry with transition to `waiting_for_approval`.
   - User approval resumes fallback (mode `lite`, fewer checks) from checkpoint without re-running done steps.
   - User refusal ends session cleanly without executing downstream calculations or drafts.
   - Idempotency: duplicate messages / replays do not re-run pipeline steps or duplicate audit entries.
   - Serialization across session restart mid-workflow.
   - Draft finalization approval gate (`keep_package`).
   - Append-only audit trail logging with secret redaction (`render_audit_trail`).
   - AST code scan: zero unauthorized external communications (no SMTP, no non-ASI `requests.post`).

5. **Multi-Agent uAgents & Agent Chat Protocol (`tests/test_recovery.py`)**:
   - `recoverpay-verifier` never replies when `FORCE_FAIL=true` is set.
   - `recoverpay-verifier` returns full evidence check when normal.
   - `recoverpay-fallback` executes mode `lite` and attaches fewer checks notice.
   - `recoverpay-drafter` returns prepared drafts for review.
   - Orchestrator `on_interval` timeout monitor detects unresponsive specialists, issues single retry, and prompts user for fallback.
   - Duplicate specialist response idempotency.
   - ASI:One live path functions (free-text case extraction, gap explanation, template draft wording) with clean offline template fallback.

6. **State Machine Transitions (`tests/test_state_machine.py`)**:
   - Eligibility gate mandatory before any case loading.
   - Interactive flow from welcome → eligibility → intake → review → done.
   - `keep_package` records approval event without sending any external communications.
