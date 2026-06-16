from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from .models import ArticleCandidate


SOURCE_TYPE_WEIGHT = {
    "official": 1.20,
    "research": 1.15,
    "finance": 1.15,
    "media": 1.00,
    "wechat": 0.85,
    "other": 0.60,
}

HIGH_VALUE_KEYWORDS = [
    "OpenAI",
    "Anthropic",
    "DeepSeek",
    "Gemini",
    "Claude",
    "GPT",
    "NVIDIA",
    "GPU",
    "export control",
    "sanction",
    "Federal Reserve",
    "inflation",
    "interest rate",
    "大模型",
    "芯片",
    "出口管制",
    "美联储",
    "降息",
    "通胀",
]


def rough_priority_score(candidate: ArticleCandidate) -> float:
    score = 45.0
    source_weight = SOURCE_TYPE_WEIGHT.get(candidate.source_type, 0.60)
    text = f"{candidate.title} {candidate.summary or ''}"
    for keyword in HIGH_VALUE_KEYWORDS:
        if keyword.lower() in text.lower():
            score += 4
    score += recency_bonus(candidate.published_at)
    score *= source_weight
    return min(round(score, 2), 100.0)


def recency_bonus(published_at: str | None) -> float:
    if not published_at:
        return 5.0
    try:
        parsed = parsedate_to_datetime(published_at)
    except (TypeError, ValueError):
        return 5.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    age_hours = max((datetime.now(timezone.utc) - parsed).total_seconds() / 3600, 0)
    if age_hours <= 24:
        return 15.0
    if age_hours <= 72:
        return 10.0
    if age_hours <= 168:
        return 5.0
    return 0.0

