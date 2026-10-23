"""Scheme-readiness checklist.

Produces a draft list of documents held and missing for a scheme.
It never decides, scores or ranks anything about the business.
All document requirements must come from data/schemes.json with a source.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CHECKLIST_LABEL = "Draft checklist, confirm with the lender or official portal"
DEFAULT_SCHEMES_PATH = Path(__file__).resolve().parent.parent / "data" / "schemes.json"
FORBIDDEN_WORDS = ("eligible", "eligibility", "qualify", "qualifies", "qualified", "approved", "guaranteed")


class ConsentRequired(Exception):
    """The user has not given consent to use their business details."""


class SchemeRulesNotVerified(Exception):
    """The scheme or one of its documents has no verified source."""


class ForbiddenLanguage(Exception):
    """Output contained a word that implies a decision about the business."""


@dataclass
class Profile:
    business_type: str
    registration_status: str
    documents_held: list[str] = field(default_factory=list)
    consent_given: bool = False


@dataclass
class ReadinessResult:
    scheme: str
    held: list[dict[str, str]]
    missing: list[dict[str, str]]
    sources: list[str]
    label: str = CHECKLIST_LABEL


def load_schemes(path: Path | str = DEFAULT_SCHEMES_PATH) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _find_scheme(schemes: dict[str, Any], name: str) -> dict[str, Any]:
    for scheme in schemes.get("schemes", []):
        if _norm(scheme.get("name") or "") == _norm(name):
            return scheme
    raise SchemeRulesNotVerified(f"Scheme '{name}' is not in the schemes file")


def _check_verified(scheme: dict[str, Any]) -> None:
    documents = scheme.get("required_documents") or []
    if not documents:
        raise SchemeRulesNotVerified(f"{scheme.get('name')}: no required documents listed")
    for doc in documents:
        url = doc.get("source_url")
        if doc.get("verified") is not True or not isinstance(url, str) or not url.startswith("http"):
            raise SchemeRulesNotVerified(
                f"{scheme.get('name')}: document '{doc.get('name')}' has no verified source"
            )


def assert_clean(text: str) -> None:
    lowered = text.lower()
    for word in FORBIDDEN_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", lowered):
            raise ForbiddenLanguage(f"Output contains forbidden word: {word}")


def readiness_checklist(profile: Profile, scheme_name: str, schemes: dict[str, Any]) -> ReadinessResult:
    if profile.consent_given is not True:
        raise ConsentRequired("Consent is required before using business details")
    scheme = _find_scheme(schemes, scheme_name)
    _check_verified(scheme)

    held_names = {_norm(d) for d in profile.documents_held}
    held: list[dict[str, str]] = []
    missing: list[dict[str, str]] = []
    for doc in scheme["required_documents"]:
        entry = {"name": doc["name"], "source_url": doc["source_url"]}
        (held if _norm(doc["name"]) in held_names else missing).append(entry)

    result = ReadinessResult(
        scheme=scheme["name"],
        held=held,
        missing=missing,
        sources=sorted({d["source_url"] for d in scheme["required_documents"]}),
    )
    assert_clean(render_checklist(result))
    return result


def render_checklist(result: ReadinessResult) -> str:
    lines = [result.label, f"Scheme: {result.scheme}", "", "Documents you have:"]
    lines += [f"- {d['name']} (source: {d['source_url']})" for d in result.held] or ["- none listed"]
    lines += ["", "Documents still missing:"]
    lines += [f"- {d['name']} (source: {d['source_url']})" for d in result.missing] or ["- none"]
    return "\n".join(lines)