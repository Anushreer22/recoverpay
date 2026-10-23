import dataclasses

import pytest

from core.readiness import (
    CHECKLIST_LABEL,
    ConsentRequired,
    ForbiddenLanguage,
    Profile,
    SchemeRulesNotVerified,
    load_schemes,
    readiness_checklist,
    render_checklist,
)

# TEST ONLY, not real requirements
FAKE = {
    "schemes": [
        {
            "name": "Test Scheme",
            "required_documents": [
                {"name": "Doc A", "source_url": "https://example.test/a", "verified": True},
                {"name": "Doc B", "source_url": "https://example.test/b", "verified": True},
            ],
        }
    ]
}


def profile(consent=True, docs=("doc a",)):
    return Profile("tailor", "registered", list(docs), consent)


def test_consent_required():
    with pytest.raises(ConsentRequired):
        readiness_checklist(profile(consent=False), "Test Scheme", FAKE)


def test_real_unfilled_file_is_rejected():
    schemes = load_schemes()
    for name in ("MUDRA", "PMEGP", "Stand-Up India", "CGTMSE"):
        with pytest.raises(SchemeRulesNotVerified):
            readiness_checklist(profile(), name, schemes)


def test_unknown_scheme_rejected():
    with pytest.raises(SchemeRulesNotVerified):
        readiness_checklist(profile(), "Nope", FAKE)


def test_unverified_document_rejected():
    bad = {"schemes": [{"name": "X", "required_documents": [{"name": "D", "source_url": None, "verified": True}]}]}
    with pytest.raises(SchemeRulesNotVerified):
        readiness_checklist(profile(), "X", bad)


def test_held_and_missing_lists():
    result = readiness_checklist(profile(docs=(" DOC  a ",)), "test scheme", FAKE)
    assert [d["name"] for d in result.held] == ["Doc A"]
    assert [d["name"] for d in result.missing] == ["Doc B"]
    assert result.sources == ["https://example.test/a", "https://example.test/b"]


def test_label_present_and_no_forbidden_words():
    result = readiness_checklist(profile(), "Test Scheme", FAKE)
    text = render_checklist(result)
    assert CHECKLIST_LABEL in text
    for word in ("eligible", "qualify", "approved", "guaranteed"):
        assert word not in text.lower()


def test_forbidden_word_in_source_data_is_blocked():
    bad = {"schemes": [{"name": "X", "required_documents": [
        {"name": "Proof you are eligible", "source_url": "https://example.test/x", "verified": True}]}]}
    with pytest.raises(ForbiddenLanguage):
        readiness_checklist(profile(), "X", bad)


def test_no_sensitive_fields_in_profile():
    names = {f.name for f in dataclasses.fields(Profile)}
    for banned in ("gender", "sex", "caste", "religion", "region", "state", "district"):
        assert banned not in names