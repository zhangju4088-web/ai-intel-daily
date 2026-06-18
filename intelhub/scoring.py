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

HOT_MODEL_KEYWORDS = [
    "GLM",
    "ChatGLM",
    "Zhipu",
    "智谱",
    "Qwen",
    "通义",
    "DeepSeek",
    "Kimi",
    "Moonshot",
    "MiniMax",
    "StepFun",
    "阶跃星辰",
    "Doubao",
    "豆包",
    "ERNIE",
    "文心",
    "Hunyuan",
    "混元",
    "Baichuan",
    "百川",
    "Yi-Lightning",
    "零一万物",
]

MODEL_RELEASE_CONTEXT = [
    "release",
    "launch",
    "introduce",
    "open-source",
    "open source",
    "built for",
    "long-horizon",
    "reasoning",
    "agent",
    "benchmark",
    "leaderboard",
    "model",
    "发布",
    "推出",
    "开源",
    "模型",
    "推理",
    "长周期",
    "智能体",
    "评测",
    "榜首",
    "登顶",
    "第一",
]

MODEL_LEADERBOARD_CONTEXT = [
    "leaderboard",
    "top",
    "rank",
    "榜首",
    "登顶",
    "第一",
]


def rough_priority_score(candidate: ArticleCandidate) -> float:
    score = 45.0
    source_weight = SOURCE_TYPE_WEIGHT.get(candidate.source_type, 0.60)
    text = f"{candidate.title} {candidate.summary or ''}"
    for keyword in HIGH_VALUE_KEYWORDS:
        if keyword.lower() in text.lower():
            score += 4
    score += hot_model_release_bonus(text)
    score += recency_bonus(candidate.published_at)
    score *= source_weight
    return min(round(score, 2), 100.0)


def hot_model_release_bonus(text: str) -> float:
    lowered = text.lower()
    has_hot_model = any(keyword.lower() in lowered for keyword in HOT_MODEL_KEYWORDS)
    if not has_hot_model:
        return 0.0

    bonus = 8.0
    if any(keyword.lower() in lowered for keyword in MODEL_RELEASE_CONTEXT):
        bonus += 4.0
    if "glm-5.2" in lowered or "glm 5.2" in lowered or "glm5.2" in lowered:
        bonus += 12.0
    if any(keyword.lower() in lowered for keyword in MODEL_LEADERBOARD_CONTEXT):
        bonus += 4.0
    return bonus


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
