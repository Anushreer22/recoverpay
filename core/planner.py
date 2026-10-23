from __future__ import annotations

from typing import Any
from core.models import Session

CREDIT_KEYWORDS = (
    "credit",
    "loan",
    "loans",
    "borrow",
    "borrowing",
    "lender",
    "lending",
    "finance",
    "financing",
    "scheme",
    "schemes",
    "mudra",
    "pmegp",
    "stand-up india",
    "standup india",
    "cgtmse",
)


class Planner:
    """Recommends next steps based on session context and user inquiries."""

    DEFAULT_STEPS = ["reconcile_case", "prepare_drafts"]
    SCHEME_READINESS_STEP = "scheme_readiness"

    @classmethod
    def is_credit_query(cls, text: str) -> bool:
        if not text:
            return False
        lowered = text.lower()
        return any(kw in lowered for kw in CREDIT_KEYWORDS)

    @classmethod
    def get_recommended_steps(
        cls, user_text: str = "", session: Session | None = None
    ) -> list[str]:
        steps = list(cls.DEFAULT_STEPS)
        if cls.is_credit_query(user_text):
            steps.append(cls.SCHEME_READINESS_STEP)
        return steps

    def recommend_next_steps(
        self, user_text: str = "", session: Session | None = None
    ) -> list[str]:
        return self.get_recommended_steps(user_text, session)

    def plan(
        self, user_text: str = "", session: Session | None = None
    ) -> list[str]:
        return self.get_recommended_steps(user_text, session)


planner = Planner()


def get_recommended_steps(
    user_text: str = "", session: Session | None = None
) -> list[str]:
    return planner.get_recommended_steps(user_text, session)


def recommend_next_steps(
    user_text: str = "", session: Session | None = None
) -> list[str]:
    return planner.recommend_next_steps(user_text, session)

