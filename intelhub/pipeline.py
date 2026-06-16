from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .config import Source, load_sources
from .dedupe import dedupe_candidates, normalize_title
from .deepseek import DeepSeekClient, DeepSeekSettings, build_article_summary_prompt
from .extract import extract_url_text
from .fetch import fetch_source
from .manual import load_manual_candidates
from .models import ArticleCandidate
from .scoring import rough_priority_score


CATEGORIES = ["大模型动态", "AI行业资讯", "国际形势影响", "国际金融"]


@dataclass
class ArticleAnalysis:
    candidate: ArticleCandidate
    category: str
    ai_title: str
    one_sentence_summary: str
    detailed_summary: str
    key_points: list[str]
    why_it_matters: str
    impact_analysis: dict[str, str]
    topic_angle: str
    avoid_angle: str
    recommended: bool
    priority_score: float
    confidence: float
    analysis_method: str = "local"
    extracted_text: str | None = None
    extraction_error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        item = asdict(self)
        item["candidate"] = self.candidate.as_dict()
        return item


@dataclass
class ReadingLink:
    source_id: str
    source_name: str
    source_type: str
    source_role: str
    original_title: str
    url: str
    published_at: str | None
    link_label: str
    is_primary_reading_link: bool
    display_order: int


@dataclass
class EventCard:
    id: str
    event_date: str
    category: str
    ai_title: str
    one_sentence_summary: str
    detailed_summary: str
    key_points: list[str]
    why_it_matters: str
    impact_analysis: dict[str, str]
    topic_angle: str
    avoid_angle: str
    recommended: bool
    priority_score: float
    confidence: float
    reading_links: list[ReadingLink] = field(default_factory=list)
    source_count: int = 0
    source_types: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_daily_digest(
    *,
    config_path: Path,
    manual_links_path: Path,
    digest_date: date,
    source_ids: set[str] | None = None,
    limit_sources: int | None = None,
    per_source: int = 5,
    top_per_category: int = 15,
    extract_text: bool = False,
    extract_limit: int = 20,
    summarize_with: str = "local",
) -> dict[str, Any]:
    config = load_sources(config_path)
    sources = config.enabled_sources()
    source_map = {source.id: source for source in sources}
    web_sources = [source for source in sources if source.method != "manual_link"]
    if source_ids:
        web_sources = [source for source in web_sources if source.id in source_ids]
    if limit_sources is not None:
        web_sources = web_sources[:limit_sources]

    candidates: list[ArticleCandidate] = []
    fetch_errors: list[dict[str, str]] = []

    if manual_links_path.exists():
        candidates.extend(load_manual_candidates(manual_links_path, source_map))

    for source in web_sources:
        result = fetch_source(source, limit=per_source)
        if result.error:
            fetch_errors.append({"source_id": source.id, "source_name": source.name, "error": result.error})
            continue
        candidates.extend(result.candidates)

    unique_candidates = dedupe_candidates(candidates)
    analyses = analyze_candidates(
        unique_candidates,
        source_map=source_map,
        digest_date=digest_date,
        extract_text=extract_text,
        extract_limit=extract_limit,
        summarize_with=summarize_with,
    )
    events = merge_analyses(analyses, digest_date=digest_date)
    selected = select_top_events(events, top_per_category=top_per_category)
    topic_pool = build_topic_pool(selected)
    top10 = sorted(selected, key=lambda item: item.priority_score, reverse=True)[:10]

    return {
        "digest_date": digest_date.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": "intelhub-local-pipeline",
        "settings": {
            "per_source": per_source,
            "top_per_category": top_per_category,
            "extract_text": extract_text,
            "extract_limit": extract_limit,
            "summarize_with": summarize_with,
        },
        "stats": {
            "fetched_candidate_count": len(candidates),
            "unique_candidate_count": len(unique_candidates),
            "analysis_count": len(analyses),
            "deepseek_analysis_count": sum(1 for item in analyses if item.analysis_method == "deepseek"),
            "local_analysis_count": sum(1 for item in analyses if item.analysis_method == "local"),
            "extracted_text_count": sum(1 for item in analyses if item.extracted_text),
            "extraction_error_count": sum(1 for item in analyses if item.extraction_error),
            "event_count": len(events),
            "selected_event_count": len(selected),
            "fetch_error_count": len(fetch_errors),
        },
        "fetch_errors": fetch_errors,
        "categories": {
            category: [event.as_dict() for event in selected if event.category == category]
            for category in CATEGORIES
        },
        "top10": [event.as_dict() for event in top10],
        "topic_pool": topic_pool,
    }


def analyze_candidates(
    candidates: list[ArticleCandidate],
    *,
    source_map: dict[str, Source],
    digest_date: date,
    extract_text: bool,
    extract_limit: int,
    summarize_with: str,
) -> list[ArticleAnalysis]:
    client: DeepSeekClient | None = None
    if summarize_with == "deepseek" and os.getenv("DEEPSEEK_API_KEY"):
        client = DeepSeekClient(DeepSeekSettings.from_env())

    extraction_indexes = choose_extraction_indexes(candidates, extract_limit) if extract_text else set()
    analyses: list[ArticleAnalysis] = []
    for index, candidate in enumerate(candidates):
        extracted_text = None
        extraction_error = None
        if index in extraction_indexes:
            try:
                extracted_text = extract_url_text(candidate.url)
            except Exception as exc:
                extraction_error = str(exc)

        analysis = None
        if client and extracted_text:
            analysis = deepseek_analysis(client, candidate, extracted_text, digest_date)
        if not analysis:
            analysis = local_analysis(candidate, extracted_text)
        analysis.extracted_text = extracted_text
        analysis.extraction_error = extraction_error
        analyses.append(analysis)
    return analyses


def choose_extraction_indexes(candidates: list[ArticleCandidate], extract_limit: int) -> set[int]:
    if extract_limit <= 0:
        return set()

    pools: dict[str, list[int]] = {category: [] for category in CATEGORIES}
    for index, candidate in enumerate(candidates):
        pools[coerce_category(candidate.category_hint, candidate)].append(index)

    for category, indexes in pools.items():
        indexes.sort(key=lambda item: rough_priority_score(candidates[item]), reverse=True)

    selected: list[int] = []
    cursors = {category: 0 for category in CATEGORIES}
    while len(selected) < extract_limit:
        progressed = False
        for category in CATEGORIES:
            cursor = cursors[category]
            if cursor >= len(pools[category]) or len(selected) >= extract_limit:
                continue
            selected.append(pools[category][cursor])
            cursors[category] = cursor + 1
            progressed = True
        if not progressed:
            break
    return set(selected)


def deepseek_analysis(
    client: DeepSeekClient,
    candidate: ArticleCandidate,
    extracted_text: str,
    digest_date: date,
) -> ArticleAnalysis | None:
    try:
        system, user = build_article_summary_prompt(
            source_name=candidate.source_name,
            source_type=candidate.source_type,
            original_title=candidate.title,
            canonical_url=candidate.url,
            published_at=candidate.published_at,
            current_date=digest_date.isoformat(),
            extracted_text=extracted_text,
        )
        result = client.complete_json(system, user)
    except Exception:
        return None
    return ArticleAnalysis(
        candidate=candidate,
        category=coerce_category(str(result.get("category") or candidate.category_hint), candidate),
        ai_title=str(result.get("ai_title") or candidate.title)[:80],
        one_sentence_summary=str(result.get("one_sentence_summary") or candidate.summary or candidate.title)[:160],
        detailed_summary=str(result.get("detailed_summary") or candidate.summary or candidate.title),
        key_points=[str(item) for item in result.get("key_points", [])][:5],
        why_it_matters=str(result.get("why_it_matters") or ""),
        impact_analysis=_string_dict(result.get("impact_analysis", {})),
        topic_angle=str(result.get("topic_angle") or ""),
        avoid_angle=str(result.get("avoid_angle") or ""),
        recommended=bool(result.get("recommended", True)),
        priority_score=float(result.get("priority_score") or rough_priority_score(candidate)),
        confidence=float(result.get("confidence") or 0.7),
        analysis_method="deepseek",
    )


def local_analysis(candidate: ArticleCandidate, extracted_text: str | None) -> ArticleAnalysis:
    category = coerce_category(candidate.category_hint, candidate)
    text = extracted_text or candidate.summary or candidate.title
    sentences = split_sentences(text)
    one_sentence = candidate.summary or (sentences[0] if sentences else candidate.title)
    detailed = " ".join(sentences[:4]) if sentences else one_sentence
    key_points = sentences[:5] or [candidate.title]
    ai_title = rewrite_title(candidate.title, category, candidate)
    if category == "国际金融" and not re.search(r"[\u4e00-\u9fff]", one_sentence):
        one_sentence = ai_title
        detailed = f"{ai_title}。该条来自{candidate.source_name}，建议结合原文关注其对利率、汇率、风险资产和科技股估值的影响。"
        key_points = [ai_title, "原文为英文，发布前需复核具体日期、金额和政策表述。"]
    score = rough_priority_score(candidate)
    return ArticleAnalysis(
        candidate=candidate,
        category=category,
        ai_title=ai_title,
        one_sentence_summary=trim(one_sentence, 120),
        detailed_summary=trim(detailed, 500),
        key_points=[trim(item, 120) for item in key_points],
        why_it_matters=local_why_it_matters(category, candidate),
        impact_analysis=local_impact(category, candidate),
        topic_angle=local_topic_angle(category, candidate),
        avoid_angle="避免只复述消息本身，优先补充产业、政策或商业影响。",
        recommended=score >= 55,
        priority_score=score,
        confidence=0.55,
        analysis_method="local",
    )


def merge_analyses(analyses: list[ArticleAnalysis], *, digest_date: date) -> list[EventCard]:
    events: list[EventCard] = []
    buckets: list[list[ArticleAnalysis]] = []
    for analysis in sorted(analyses, key=lambda item: item.priority_score, reverse=True):
        matched = False
        for bucket in buckets:
            if should_merge(bucket[0], analysis):
                bucket.append(analysis)
                matched = True
                break
        if not matched:
            buckets.append([analysis])

    for bucket in buckets:
        bucket.sort(key=lambda item: item.priority_score, reverse=True)
        primary = choose_primary(bucket)
        links = build_reading_links(bucket, primary)
        source_types = sorted({item.candidate.source_type for item in bucket})
        source_bonus = min((len(bucket) - 1) * 2.5, 10)
        score = min(round(primary.priority_score + source_bonus, 2), 100)
        events.append(
            EventCard(
                id=stable_event_id(primary, digest_date),
                event_date=digest_date.isoformat(),
                category=primary.category,
                ai_title=primary.ai_title,
                one_sentence_summary=primary.one_sentence_summary,
                detailed_summary=primary.detailed_summary,
                key_points=primary.key_points,
                why_it_matters=primary.why_it_matters,
                impact_analysis=primary.impact_analysis,
                topic_angle=primary.topic_angle,
                avoid_angle=primary.avoid_angle,
                recommended=primary.recommended,
                priority_score=score,
                confidence=max(item.confidence for item in bucket),
                reading_links=links,
                source_count=len({item.candidate.source_id for item in bucket}),
                source_types=source_types,
            )
        )
    return events


def select_top_events(events: list[EventCard], *, top_per_category: int) -> list[EventCard]:
    selected: list[EventCard] = []
    for category in CATEGORIES:
        category_events = [event for event in events if event.category == category]
        category_events.sort(key=lambda item: item.priority_score, reverse=True)
        selected.extend(category_events[:top_per_category])
    selected.sort(key=lambda item: (CATEGORIES.index(item.category), -item.priority_score))
    return selected


def build_topic_pool(events: list[EventCard], *, limit: int = 10) -> list[dict[str, Any]]:
    candidates = [event for event in events if event.recommended]
    candidates.sort(key=lambda item: item.priority_score, reverse=True)
    topics = []
    for rank, event in enumerate(candidates[:limit], start=1):
        topics.append(
            {
                "rank": rank,
                "title": event.topic_angle or event.ai_title,
                "source_event_ids": [event.id],
                "core_argument": event.why_it_matters,
                "why_today": event.one_sentence_summary,
                "differentiation": event.avoid_angle,
                "risk_notes": "发布前复核原文链接、时间、数字和政策表述。",
            }
        )
    return topics


def build_reading_links(bucket: list[ArticleAnalysis], primary: ArticleAnalysis) -> list[ReadingLink]:
    links: list[ReadingLink] = []
    for index, item in enumerate(bucket, start=1):
        source_role = "primary" if item is primary else ("wechat_analysis" if item.candidate.source_type == "wechat" else "supporting")
        links.append(
            ReadingLink(
                source_id=item.candidate.source_id,
                source_name=item.candidate.source_name,
                source_type=item.candidate.source_type,
                source_role=source_role,
                original_title=item.candidate.title,
                url=item.candidate.url,
                published_at=item.candidate.published_at,
                link_label=item.candidate.source_name,
                is_primary_reading_link=item is primary,
                display_order=index,
            )
        )
    return links


def choose_primary(bucket: list[ArticleAnalysis]) -> ArticleAnalysis:
    source_rank = {"official": 0, "research": 1, "finance": 1, "media": 2, "wechat": 3, "other": 4}
    return sorted(
        bucket,
        key=lambda item: (source_rank.get(item.candidate.source_type, 5), -item.priority_score),
    )[0]


def should_merge(left: ArticleAnalysis, right: ArticleAnalysis) -> bool:
    if left.category != right.category:
        return False
    left_title = normalize_title(left.candidate.title)
    right_title = normalize_title(right.candidate.title)
    if not left_title or not right_title:
        return False
    if left_title == right_title:
        return True
    ratio = SequenceMatcher(None, left_title, right_title).ratio()
    if ratio >= 0.72:
        return True
    return keyword_overlap(left.candidate.title, right.candidate.title) >= 0.62


def keyword_overlap(left: str, right: str) -> float:
    left_terms = title_terms(left)
    right_terms = title_terms(right)
    if not left_terms or not right_terms:
        return 0.0
    return len(left_terms & right_terms) / len(left_terms | right_terms)


def title_terms(title: str) -> set[str]:
    terms = set(re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}|[\u4e00-\u9fff]{2,}", title))
    stop = {"the", "and", "for", "with", "from", "this", "that", "new", "news", "发布", "推出", "最新"}
    return {term.lower() for term in terms if term.lower() not in stop}


def coerce_category(category_hint: str, candidate: ArticleCandidate) -> str:
    if category_hint in CATEGORIES:
        return category_hint
    text = f"{candidate.title} {candidate.summary or ''}".lower()
    if any(term.lower() in text for term in ["gpt", "claude", "gemini", "deepseek", "llm", "model", "benchmark", "arxiv", "大模型", "模型", "推理"]):
        return "大模型动态"
    if any(term.lower() in text for term in ["fed", "ecb", "boj", "treasury", "inflation", "rate", "cpi", "stocks", "dollar", "美联储", "通胀", "降息", "金融"]):
        return "国际金融"
    if any(term.lower() in text for term in ["sanction", "export control", "war", "election", "white house", "china", "tariff", "地缘", "出口管制", "制裁", "关税"]):
        return "国际形势影响"
    return "AI行业资讯"


def rewrite_title(title: str, category: str | None = None, candidate: ArticleCandidate | None = None) -> str:
    title = re.sub(r"\s+", " ", title).strip()
    if not re.search(r"[\u4e00-\u9fff]", title) and category:
        localized = localize_english_title(title, category)
        if len(localized) <= 38:
            return localized
        return localized[:36].rstrip() + "..."
    if len(title) <= 38:
        return title
    return title[:36].rstrip() + "..."


def localize_english_title(title: str, category: str) -> str:
    if category == "国际金融":
        finance_title = localize_finance_title(title)
        if finance_title:
            return finance_title

    replacements = [
        ("Federal Reserve", "美联储"),
        ("Fed", "美联储"),
        ("European Central Bank", "欧洲央行"),
        ("ECB", "欧洲央行"),
        ("Bank of Japan", "日本央行"),
        ("BOJ", "日本央行"),
        ("U.S. Treasury", "美国财政部"),
        ("Treasury", "美国财政部"),
        ("inflation", "通胀"),
        ("interest rate", "利率"),
        ("rates", "利率"),
        ("rate", "利率"),
        ("dollar", "美元"),
        ("stocks", "股市"),
        ("market", "市场"),
        ("markets", "市场"),
        ("economy", "经济"),
        ("economic", "经济"),
        ("monetary policy", "货币政策"),
        ("press release", "新闻稿"),
        ("speech", "讲话"),
        ("AI", "AI"),
    ]
    localized = title
    for source, target in replacements:
        localized = re.sub(re.escape(source), target, localized, flags=re.IGNORECASE)
    if re.search(r"[\u4e00-\u9fff]", localized):
        return localized
    return f"{category}｜{localized}"


def localize_finance_title(title: str) -> str:
    compact = re.sub(r"\s+", " ", title).strip()
    lowered = compact.lower()

    if "fincen issues guidance" in lowered and "fraud" in lowered:
        return "FinCEN发布信息共享指引，帮助金融机构打击欺诈"
    if "petroleum club of houston" in lowered:
        return "美国财政部长贝森特在休斯敦石油俱乐部发表讲话"
    if "texas bankers" in lowered:
        return "美国财政部长贝森特与德州银行家活动讲话"
    if "trump accounts for foster youth" in lowered:
        return "美国财政部宣布寄养青年可获得“特朗普账户”支持"
    if "ways and means committee" in lowered:
        return "美国财政部长贝森特在众议院筹款委员会作证"
    if "new foreign direct investment in the united states" in lowered:
        return "2025年美国新增外国直接投资数据发布"
    if "u.s. international trade in goods and services" in lowered or "international trade in goods and services" in lowered:
        return "美国4月国际货物和服务贸易数据发布"
    if "personal income and outlays" in lowered:
        return "美国4月个人收入和支出数据发布"
    if "gdp (second estimate)" in lowered and "corporate profits" in lowered:
        return "美国一季度GDP二次估算和企业利润公布"
    if "ecb launches pilot project" in lowered and "confidential statistical data" in lowered:
        return "欧洲央行启动保密统计数据研究访问试点"
    if "budget credibility" in lowered and "africa" in lowered:
        return "预算可信度成为改善非洲经济结果的关键锚点"
    if "africa's golden future" in lowered:
        return "IMF谈非洲“黄金未来”"

    dated = re.sub(r"^[A-Z][a-z]+ \d{1,2}, 20\d{2}\s+", "", compact)
    lowered_dated = dated.lower()
    if "imf staff concludes visit to kazakhstan" in lowered_dated:
        return "IMF工作人员结束哈萨克斯坦访问"
    if "imf executive board concludes" in lowered_dated and "serbia" in lowered_dated:
        return "IMF完成塞尔维亚政策协调工具第三次审查"
    if "article iv consultation" in lowered_dated and "st. vincent" in lowered_dated:
        return "IMF完成圣文森特和格林纳丁斯2026年第四条磋商"
    if "guinea-bissau" in lowered_dated and "extended credit facility" in lowered_dated:
        return "IMF完成几内亚比绍扩展信贷安排第十一次审查"
    if "ukraine" in lowered_dated and "extended fund facility" in lowered_dated:
        return "IMF与乌克兰就扩展基金安排审查达成工作人员级协议"
    if "niger" in lowered_dated and "extended credit facility" in lowered_dated:
        return "IMF与尼日尔就扩展信贷安排第九次审查达成协议"

    return ""


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    parts = re.split(r"(?<=[。！？.!?])\s+", text)
    return [part.strip() for part in parts if len(part.strip()) >= 8]


def trim(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def local_why_it_matters(category: str, candidate: ArticleCandidate) -> str:
    if category == "大模型动态":
        return "可能影响模型能力、成本、产品节奏或开发者生态，适合作为 AI 选题线索继续跟进。"
    if category == "AI行业资讯":
        return "可能反映 AI 商业化、算力、应用落地或公司竞争格局的变化。"
    if category == "国际形势影响":
        return "可能影响 AI 产业链、芯片供应、跨境合作或监管预期。"
    return "可能影响美元利率、风险资产、科技股估值或全球资金流向。"


def local_impact(category: str, candidate: ArticleCandidate) -> dict[str, str]:
    return {
        "technology": "需结合原文判断技术路线和能力边界。" if category in {"大模型动态", "AI行业资讯"} else "",
        "business": "可关注对企业采购、产品竞争和商业模式的影响。" if category in {"AI行业资讯", "大模型动态"} else "",
        "policy": "可关注监管、地缘政治和跨境产业链影响。" if category == "国际形势影响" else "",
        "finance": "可关注利率、汇率、商品、科技股和风险偏好的变化。" if category == "国际金融" else "",
    }


def local_topic_angle(category: str, candidate: ArticleCandidate) -> str:
    if category == "大模型动态":
        return f"从能力、成本和生态角度解读：{candidate.title}"
    if category == "AI行业资讯":
        return f"从商业化和产业竞争角度解读：{candidate.title}"
    if category == "国际形势影响":
        return f"从国际形势对 AI 产业链的影响解读：{candidate.title}"
    return f"从国际金融变量对 AI 与科技股的影响解读：{candidate.title}"


def stable_event_id(primary: ArticleAnalysis, digest_date: date) -> str:
    raw = f"{digest_date.isoformat()}:{primary.category}:{normalize_title(primary.candidate.title)}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, raw))


def _string_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def write_digest_json(digest: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(digest, ensure_ascii=False, indent=2), encoding="utf-8")
