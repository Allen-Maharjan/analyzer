"""Apply an owner-confirmed news risk to the shown advice.

Deterministic and read-time: the saved analysis is never changed. An active confirmation
turns only BUY into WAIT. WAIT and WATCH CLOSELY stay as they are. AI output is never an
input here, so AI text alone can't change the decision.
"""

from dataclasses import dataclass
from datetime import datetime

from gold_advisor.domain import Decision


@dataclass(frozen=True)
class Risk:
    reason: str
    expires_at: datetime
    article_title: str | None
    article_publisher: str | None
    article_url: str | None


def apply(decision: dict, risk: Risk | None, now: datetime) -> tuple[dict, dict | None]:
    """Return the advice to show and, when the risk changed it, a description of the change."""
    if risk is None or risk.expires_at <= now or decision.get("decision") != Decision.BUY.value:
        return decision, None
    source = f" ({risk.article_publisher})" if risk.article_publisher else ""
    shown = {
        **decision,
        "decision": Decision.WAIT.value,
        "headline": "Wait: you flagged a news risk",
        "summary": (
            f"The numbers point to buying, but you marked a news story{source} as a reason to wait. "
            "This lasts until the story is a day old, or until you clear it."
        ),
        "next_review": "When the news risk expires or you clear it.",
        "what_would_change": "Clearing the news risk brings back the Buy advice, if the numbers still support it.",
        "rule": "owner_news_risk",
    }
    override = {
        "original_decision": decision.get("decision"),
        "reason": risk.reason,
        "expires_at": risk.expires_at,
        "article_title": risk.article_title,
        "article_publisher": risk.article_publisher,
        "article_url": risk.article_url,
    }
    return shown, override
