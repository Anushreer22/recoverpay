from __future__ import annotations

import hashlib
import json
import os
from abc import ABC, abstractmethod
from typing import Any

from core.calc import reconcile_case
from core.models import CasePackage, Finding, ReconcileResult, to_dict


class ReconcilerTimeout(Exception):
    """Raised when the reconciler service times out."""


class ReconcilerClient(ABC):
    """Interface for reconciling case packages."""

    @abstractmethod
    def reconcile(self, case: CasePackage, mode: str = "full") -> ReconcileResult:
        """Reconciles a case package, returning ReconcileResult or raising ReconcilerTimeout."""
        raise NotImplementedError


class InProcessReconciler(ReconcilerClient):
    """In-process reconciler implementation calling core.calc.reconcile_case."""

    def reconcile(self, case: CasePackage, mode: str = "full") -> ReconcileResult:
        return reconcile_case(case, mode=mode)


class FlakyReconciler(ReconcilerClient):
    """Wrapper that raises ReconcilerTimeout when FORCE_FAIL=true or forced programmatically."""

    def __init__(
        self,
        delegate: ReconcilerClient | None = None,
        force_fail: bool | None = None,
    ):
        self.delegate = delegate or InProcessReconciler()
        self.force_fail = force_fail

    def reconcile(self, case: CasePackage, mode: str = "full") -> ReconcileResult:
        is_forced = (
            self.force_fail
            if self.force_fail is not None
            else os.getenv("FORCE_FAIL", "").strip().lower() in {"true", "1", "yes"}
        )
        if is_forced:
            raise ReconcilerTimeout("Reconciler timed out: service did not respond (FORCE_FAIL=true)")
        return self.delegate.reconcile(case, mode=mode)


# Convenience alias
LocalReconciler = InProcessReconciler


def make_step_key(case_id: str, step_name: str, inputs: Any) -> str:
    """Generates an idempotency key from case_id, step_name, and a sha256 hash of inputs."""
    if hasattr(inputs, "__dataclass_fields__"):
        serialized = json.dumps(to_dict(inputs), sort_keys=True, default=str)
    elif isinstance(inputs, (dict, list, tuple, str, int, float, bool)):
        serialized = json.dumps(inputs, sort_keys=True, default=str)
    else:
        serialized = str(inputs)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]
    return f"{case_id}:{step_name}:{digest}"


def run_fallback_reconciliation(case: CasePackage) -> ReconcileResult:
    """Executes rule-based fallback reconciliation in mode 'lite' with fewer checks."""
    result = reconcile_case(case, mode="lite")
    note_msg = "Rule-based fallback (mode lite) used fewer checks than full reconciliation."
    if not any("fewer checks" in f.message.lower() for f in result.findings):
        result.findings.append(
            Finding(code="fallback_fewer_checks", severity="info", message=note_msg)
        )
    if not result.notes:
        result.notes = note_msg
    elif "fewer checks" not in result.notes.lower():
        result.notes = f"{result.notes}\n{note_msg}".strip()
    return result

