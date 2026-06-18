from __future__ import annotations

import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Iterable

from .models import ArticleCandidate


SOURCE_TYPE_BONUS = {
    "official": 18.0,
    "research": 11.0,
    "finance": 10.0,
    "media": 7.0,
    "wechat": 5.0,
    "other": -4.0,
}

KEY_ENTITY_TERMS = [
    "OpenAI",
    "Anthropic",
    "Claude",
    "Google DeepMind",
    "Gemini",
    "DeepSeek",
    "Zhipu",
    "智谱",
    "GLM",
    "ChatGLM",
    "Qwen",
    "通义",
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
    "NVIDIA",
    "Blackwell",
    "GPU",
    "Meta AI",
    "Llama",
    "xAI",
    "Grok",
    "Mistral",
    "Hugging Face",
    "Microsoft",
    "微软",
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
    "Claude",
    "GPT",
    "Gemini",
    "Llama",
    "Mistral",
]

MODEL_RELEASE_CONTEXT = [
    "release",
    "released",
    "launch",
    "launched",
    "introduce",
    "introduced",
    "unveil",
    "unveiled",
    "open-source",
    "open source",
    "built for",
    "model",
    "reasoning",
    "agent",
    "coding",
    "long-horizon",
    "long context",
    "benchmark",
    "leaderboard",
    "sota",
    "发布",
    "推出",
    "开源",
    "模型",
    "推理",
    "智能体",
    "编程",
    "长周期",
    "长程",
    "长上下文",
    "评测",
    "基准",
    "榜单",
    "榜首",
    "登顶",
    "第一",
]

MODEL_BENCHMARK_CONTEXT = [
    "benchmark",
    "leaderboard",
    "arena",
    "swe-bench",
    "frontierswe",
    "posttrainbench",
    "terminal-bench",
    "swe-marathon",
    "mlperf",
    "sota",
    "ranking",
    "rank",
    "top",
    "基准",
    "评测",
    "榜单",
    "榜首",
    "登顶",
    "第一",
    "超越",
]

CODING_CONTEXT = [
    "coding",
    "code",
    "developer",
    "software engineering",
    "swe",
    "agentic coding",
    "编程",
    "代码",
    "开发者",
    "工程任务",
    "软件工程",
]

AI_INDUSTRY_CONTEXT = [
    "funding",
    "valuation",
    "acquisition",
    "partnership",
    "enterprise",
    "pricing",
    "subscription",
    "revenue",
    "data center",
    "datacenter",
    "compute",
    "chip",
    "gpu",
    "blackwell",
    "cuda",
    "cloud",
    "product",
    "developer",
    "投资",
    "融资",
    "估值",
    "收购",
    "合作",
    "企业",
    "定价",
    "订阅",
    "收入",
    "数据中心",
    "算力",
    "芯片",
    "云",
    "产品",
    "商业化",
]

GEOPOLITICAL_CONTEXT = [
    "export control",
    "export controls",
    "sanction",
    "sanctions",
    "tariff",
    "white house",
    "congress",
    "china",
    "taiwan",
    "war",
    "military",
    "election",
    "regulation",
    "antitrust",
    "national security",
    "chip",
    "chips",
    "semiconductor",
    "semiconductors",
    "出口管制",
    "制裁",
    "关税",
    "白宫",
    "国会",
    "中国",
    "台湾",
    "战争",
    "军事",
    "大选",
    "监管",
    "反垄断",
    "国家安全",
    "地缘",
    "芯片",
    "半导体",
]

FINANCE_CONTEXT = [
    "federal reserve",
    "fed",
    "ecb",
    "boj",
    "treasury",
    "inflation",
    "cpi",
    "ppi",
    "interest rate",
    "rate cut",
    "rate hike",
    "yield",
    "dollar",
    "nasdaq",
    "s&p",
    "stock",
    "bond",
    "oil",
    "gdp",
    "jobs",
    "unemployment",
    "earnings",
    "guidance",
    "美联储",
    "欧洲央行",
    "日本央行",
    "美国财政部",
    "通胀",
    "利率",
    "降息",
    "加息",
    "收益率",
    "美元",
    "纳指",
    "股票",
    "债券",
    "原油",
    "GDP",
    "就业",
    "财报",
    "指引",
]

LOW_VALUE_CONTEXT = [
    "subscribe",
    "newsletter",
    "webinar",
    "event registration",
    "job opening",
    "hiring",
    "roundup",
    "活动报名",
    "直播预告",
    "招聘",
    "周报",
]


def rough_priority_score(candidate: ArticleCandidate) -> float:
    breakdown = priority_score_breakdown(candidate)
    return breakdown["score"]


def priority_score_breakdown(candidate: ArticleCandidate) -> dict[str, float]:
    text = candidate_text(candidate)
    category = candidate.category_hint

    components = {
        "base": 34.0,
        "source": SOURCE_TYPE_BONUS.get(candidate.source_type, SOURCE_TYPE_BONUS["other"]),
        "source_weight": source_weight_bonus(candidate.source_weight),
        "recency": recency_bonus(candidate.published_at),
        "entity": keyword_match_bonus(text, KEY_ENTITY_TERMS, points_each=3.0, cap=12.0),
        "model_release": hot_model_release_bonus(text),
        "industry": keyword_match_bonus(text, AI_INDUSTRY_CONTEXT, points_each=2.0, cap=8.0),
        "geopolitical": contextual_bonus(text, category, GEOPOLITICAL_CONTEXT, points_each=2.5, cap=12.0),
        "finance": contextual_bonus(text, category, FINANCE_CONTEXT, points_each=2.5, cap=12.0),
        "low_value_penalty": low_value_penalty(text),
    }
    raw_score = sum(components.values())
    score = min(max(round(raw_score, 2), 0.0), 100.0)
    components["score"] = score
    return components


def candidate_text(candidate: ArticleCandidate) -> str:
    return " ".join(
        [
            candidate.title or "",
            candidate.summary or "",
            candidate.source_name or "",
            candidate.category_hint or "",
        ]
    )


def source_weight_bonus(weight: float) -> float:
    return min(max(round((weight - 1.0) * 20.0, 2), -8.0), 8.0)


def keyword_match_bonus(text: str, keywords: Iterable[str], *, points_each: float, cap: float) -> float:
    hits = keyword_hits(text, keywords)
    return min(len(hits) * points_each, cap)


def contextual_bonus(
    text: str,
    category_hint: str,
    keywords: Iterable[str],
    *,
    points_each: float,
    cap: float,
) -> float:
    bonus = keyword_match_bonus(text, keywords, points_each=points_each, cap=cap)
    if not bonus:
        return 0.0
    if category_hint in {"国际形势影响", "国际金融", "AI行业资讯"}:
        bonus += 4.0
    return min(bonus, cap + 4.0)


def hot_model_release_bonus(text: str) -> float:
    lowered = text.lower()
    has_hot_model = any(keyword.lower() in lowered for keyword in HOT_MODEL_KEYWORDS)
    if not has_hot_model:
        return 0.0

    bonus = 8.0
    if keyword_hits(text, MODEL_RELEASE_CONTEXT):
        bonus += 6.0
    if keyword_hits(text, MODEL_BENCHMARK_CONTEXT):
        bonus += 6.0
    if keyword_hits(text, CODING_CONTEXT):
        bonus += 4.0
    if re.search(r"\b[A-Za-z]{2,}[- ]?\d+(?:\.\d+)+\b", text):
        bonus += 2.0
    if "glm-5.2" in lowered or "glm 5.2" in lowered or "glm5.2" in lowered:
        bonus += 8.0
    return min(bonus, 32.0)


def keyword_hits(text: str, keywords: Iterable[str]) -> set[str]:
    lowered = text.lower()
    hits: set[str] = set()
    for keyword in keywords:
        normalized = keyword.lower()
        if normalized and keyword_in_text(normalized, lowered):
            hits.add(normalized)
    return hits


def keyword_in_text(keyword: str, lowered_text: str) -> bool:
    if re.search(r"[\u4e00-\u9fff]", keyword):
        return keyword in lowered_text
    pattern = r"(?<![a-z0-9])" + re.escape(keyword).replace(r"\ ", r"\s+") + r"(?![a-z0-9])"
    return re.search(pattern, lowered_text) is not None


def low_value_penalty(text: str) -> float:
    hits = keyword_hits(text, LOW_VALUE_CONTEXT)
    if not hits:
        return 0.0
    return -min(len(hits) * 3.0, 9.0)


def recency_bonus(published_at: str | None) -> float:
    parsed = parse_published_at(published_at)
    if not parsed:
        return 6.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    age_hours = max((datetime.now(timezone.utc) - parsed).total_seconds() / 3600, 0)
    if age_hours <= 12:
        return 16.0
    if age_hours <= 24:
        return 14.0
    if age_hours <= 48:
        return 11.0
    if age_hours <= 72:
        return 8.0
    if age_hours <= 168:
        return 4.0
    if age_hours <= 336:
        return 1.0
    return 0.0


def parse_published_at(published_at: str | None) -> datetime | None:
    if not published_at:
        return None
    try:
        return parsedate_to_datetime(published_at)
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError:
        return None
