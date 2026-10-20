# Test results

Command: `python -m pytest -q`

Result: 16 passed

Coverage in this run:

- Interest figures always labelled `estimate, verify`; 45-day cap; zero when not overdue
- Eligibility gate before any case working
- Medium / unregistered / trading blocked
- PO mismatch findings
- Missing delivery proof → document-request draft only
- Forbidden legal/threat language stripped
- Keep-package path does not send
