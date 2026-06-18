from __future__ import annotations

import json
import os
import re
import sys
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
MODEL_VERSION_PREFIXES = {
    "gpt",
    "glm",
    "claude",
    "opus",
    "gemini",
    "qwen",
    "deepseek",
    "kimi",
    "llama",
    "mistral",
    "ernie",
    "hunyuan",
    "doubao",
    "baichuan",
    "yi",
}


def log_progress(message: str) -> None:
    enabled = os.getenv("INTELHUB_PROGRESS", "").lower() in {"1", "true", "yes", "on"}
    if enabled:
        print(f"[intelhub] {message}", file=sys.stderr, flush=True)


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

    log_progress(
        f"starting digest date={digest_date.isoformat()} sources={len(web_sources)} "
        f"per_source={per_source} extract_text={extract_text} extract_limit={extract_limit} summarize={summarize_with}"
    )

    if manual_links_path.exists():
        manual_candidates = load_manual_candidates(manual_links_path, source_map)
        candidates.extend(manual_candidates)
        log_progress(f"loaded manual links count={len(manual_candidates)}")

    for source_index, source in enumerate(web_sources, start=1):
        log_progress(f"fetch {source_index}/{len(web_sources)} source={source.id} method={source.method}")
        result = fetch_source(source, limit=per_source)
        if result.error:
            fetch_errors.append({"source_id": source.id, "source_name": source.name, "error": result.error})
            log_progress(f"fetch failed source={source.id} error={result.error}")
            continue
        candidates.extend(result.candidates)
        log_progress(f"fetched source={source.id} candidates={len(result.candidates)} total={len(candidates)}")

    unique_candidates = dedupe_candidates(candidates)
    log_progress(f"deduped candidates raw={len(candidates)} unique={len(unique_candidates)} errors={len(fetch_errors)}")
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
    localized_count = localize_selected_events(selected, summarize_with=summarize_with, digest_date=digest_date)
    apply_special_event_card_framing(selected)
    supporting_link_count = enrich_event_reading_links(selected, analyses)
    topic_pool = build_topic_pool(selected)
    top10 = sorted(selected, key=lambda item: item.priority_score, reverse=True)[:10]
    log_progress(
        f"selected events total={len(events)} selected={len(selected)} "
        f"localized={localized_count} topic_pool={len(topic_pool)}"
    )

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
            "title_localized_count": localized_count,
            "supporting_link_count": supporting_link_count,
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
    log_progress(f"analysis candidates={len(candidates)} extraction_targets={len(extraction_indexes)} deepseek={'on' if client else 'off'}")
    analyses: list[ArticleAnalysis] = []
    extracted_seen = 0
    for index, candidate in enumerate(candidates):
        extracted_text = None
        extraction_error = None
        if index in extraction_indexes:
            extracted_seen += 1
            log_progress(
                f"extract {extracted_seen}/{len(extraction_indexes)} source={candidate.source_id} "
                f"title={trim(candidate.title, 80)}"
            )
            try:
                extracted_text = extract_url_text(candidate.url)
                log_progress(f"extract ok chars={len(extracted_text)} source={candidate.source_id}")
            except Exception as exc:
                extraction_error = str(exc)
                log_progress(f"extract failed source={candidate.source_id} error={extraction_error}")

        analysis = None
        if client and extracted_text:
            log_progress(f"deepseek start source={candidate.source_id} title={trim(candidate.title, 80)}")
            analysis = deepseek_analysis(client, candidate, extracted_text, digest_date)
            if analysis:
                log_progress(f"deepseek ok source={candidate.source_id} category={analysis.category}")
            else:
                log_progress(f"deepseek fallback source={candidate.source_id}")
        if not analysis:
            analysis = local_analysis(candidate, extracted_text)
        analysis.extracted_text = extracted_text
        analysis.extraction_error = extraction_error
        apply_special_analysis_framing(analysis)
        analyses.append(analysis)
    log_progress(f"analysis complete total={len(analyses)}")
    return analyses


def localize_selected_events(
    events: list[EventCard],
    *,
    summarize_with: str,
    digest_date: date,
) -> int:
    if summarize_with != "deepseek" or not os.getenv("DEEPSEEK_API_KEY"):
        return 0

    targets = [event for event in events if needs_chinese_polish(event)]
    if not targets:
        return 0

    try:
        client = DeepSeekClient(DeepSeekSettings.from_env())
    except Exception as exc:
        log_progress(f"title localization unavailable error={exc}")
        return 0

    chunk_size = max(1, int(os.getenv("TITLE_LOCALIZATION_CHUNK_SIZE", "20")))
    updated = 0
    for start in range(0, len(targets), chunk_size):
        chunk = targets[start : start + chunk_size]
        log_progress(f"title localization {start + 1}-{start + len(chunk)}/{len(targets)}")
        try:
            localized_items = deepseek_localize_event_chunk(client, chunk, digest_date)
        except Exception as exc:
            log_progress(f"title localization failed error={exc}")
            continue
        by_id = {str(item.get("id")): item for item in localized_items if isinstance(item, dict)}
        for event in chunk:
            item = by_id.get(event.id)
            if not item:
                continue
            changed = apply_localized_event_fields(event, item)
            if changed:
                updated += 1
    return updated


def needs_chinese_polish(event: EventCard) -> bool:
    fields = [event.ai_title, event.one_sentence_summary, event.detailed_summary, event.topic_angle]
    return any(has_english_words(field) for field in fields)


def has_english_words(text: str) -> bool:
    return bool(re.search(r"[A-Za-z]{3,}", text or ""))


def deepseek_localize_event_chunk(
    client: DeepSeekClient,
    events: list[EventCard],
    digest_date: date,
) -> list[dict[str, Any]]:
    items = []
    for event in events:
        primary_link = event.reading_links[0] if event.reading_links else None
        items.append(
            {
                "id": event.id,
                "category": event.category,
                "source_name": primary_link.source_name if primary_link else "",
                "source_type": primary_link.source_type if primary_link else "",
                "original_title": primary_link.original_title if primary_link else event.ai_title,
                "current_title": event.ai_title,
                "current_one_sentence_summary": event.one_sentence_summary,
            }
        )

    system = """
你是一个中文 AI 情报站的标题编辑。你的任务是把入选资讯的英文标题和一句话摘要改写成简洁中文，供公众号博主快速浏览。

要求：
1. 只基于输入中的标题和已有摘要，不新增输入没有的事实。
2. 公司名、模型名、产品名、论文名可以保留英文，例如 OpenAI、Claude Code、Blackwell、MLPerf。
3. 不要保留栏目名前缀，例如“AI行业资讯｜”“大模型动态｜”。
4. 不要使用省略号，不要输出 Markdown。
5. 标题必须优先中文化，不要直接照抄英文标题。
6. 输出必须是合法 JSON。
""".strip()
    user = json.dumps(
        {
            "digest_date": digest_date.isoformat(),
            "items": items,
            "output_schema": {
                "items": [
                    {
                        "id": "原样返回",
                        "ai_title": "不超过32个中文字符；必要专名可保留英文",
                        "one_sentence_summary": "不超过60个中文字符",
                    }
                ]
            },
        },
        ensure_ascii=False,
    )
    result = client.complete_json(system, user, max_tokens=1400)
    value = result.get("items", [])
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def apply_localized_event_fields(event: EventCard, item: dict[str, Any]) -> bool:
    changed = False
    title = clean_localized_text(str(item.get("ai_title") or ""), limit=48)
    if is_useful_chinese(title):
        event.ai_title = title
        changed = True

    one_sentence = clean_localized_text(str(item.get("one_sentence_summary") or ""), limit=90)
    if is_useful_chinese(one_sentence):
        event.one_sentence_summary = one_sentence
        changed = True

    detailed = clean_localized_text(str(item.get("detailed_summary") or ""), limit=260)
    if is_useful_chinese(detailed):
        event.detailed_summary = detailed
        changed = True

    if changed and has_english_words(event.topic_angle):
        event.topic_angle = default_topic_angle(event)
    return changed


def clean_localized_text(text: str, *, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^(大模型动态|AI行业资讯|国际形势影响|国际金融)[｜|:：]\s*", "", text)
    text = text.replace("...", "").replace("…", "")
    return trim(text, limit)


def is_useful_chinese(text: str) -> bool:
    return bool(text and re.search(r"[\u4e00-\u9fff]", text))


def default_topic_angle(event: EventCard) -> str:
    if event.category == "大模型动态":
        return f"从模型能力、评测和开发者生态角度解读：{event.ai_title}"
    if event.category == "AI行业资讯":
        return f"从商业化、算力和产业竞争角度解读：{event.ai_title}"
    if event.category == "国际形势影响":
        return f"从国际形势对 AI 产业链的影响解读：{event.ai_title}"
    return f"从利率、汇率和科技股估值角度解读：{event.ai_title}"


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
    analysis = ArticleAnalysis(
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
    analysis.extracted_text = extracted_text
    apply_special_analysis_framing(analysis)
    return analysis


def apply_special_analysis_framing(analysis: ArticleAnalysis) -> bool:
    text = " ".join(
        [
            analysis.candidate.title,
            analysis.candidate.summary or "",
            analysis.ai_title,
            analysis.one_sentence_summary,
            analysis.detailed_summary,
            analysis.extracted_text or "",
        ]
    )
    if not is_glm52_coding_breakthrough(text):
        return False

    analysis.category = "大模型动态"
    analysis.ai_title = "GLM-5.2长程编程超GPT-5.5，逼近Opus 4.8"
    analysis.one_sentence_summary = (
        "在 FrontierSWE 等长程编程基准中，GLM-5.2 仅落后 Opus 4.8 约 1%，"
        "超过 GPT-5.5 和 Opus 4.7，成为最高排名开源模型。"
    )
    analysis.detailed_summary = (
        "GLM-5.2 的重点不是普通版本更新，而是开源模型在长程编程和工程任务上进入闭源旗舰第一梯队。"
        "其 1M 上下文、Coding Agent 训练和 IndexShare 架构，指向复杂项目理解、跨文件调试、长链路执行等真实开发场景。"
    )
    analysis.key_points = [
        "FrontierSWE 中 GLM-5.2 仅落后 Opus 4.8 约 1%，同时超过 GPT-5.5 和 Opus 4.7。",
        "PostTrainBench 等长程任务显示其已成为最高排名开源模型。",
        "1M 上下文和长程 Coding Agent 训练，提升复杂工程任务的连续执行能力。",
    ]
    analysis.why_it_matters = "国产开源模型开始进入 AI 编程第一梯队，可能改变开发者工具、企业私有化部署和模型成本竞争。"
    analysis.impact_analysis = {
        "technology": "长上下文、智能体编程和复杂工程任务能力成为模型竞争关键。",
        "business": "若真实工程表现稳定，企业可能用开源模型替代部分昂贵闭源编程模型。",
        "policy": "",
        "finance": "",
    }
    analysis.topic_angle = "从国产开源模型进入编程第一梯队解读：GLM-5.2超GPT-5.5逼近Opus"
    analysis.avoid_angle = "避免只写跑分胜负，重点复核榜单口径、测试场景、开源协议和真实工程可用性。"
    analysis.recommended = True
    analysis.priority_score = max(analysis.priority_score, 95.0)
    return True


def apply_special_event_card_framing(events: list[EventCard]) -> int:
    updated = 0
    for event in events:
        text = " ".join(
            [
                event.ai_title,
                event.one_sentence_summary,
                event.detailed_summary,
                " ".join(event.key_points),
                " ".join(link.original_title for link in event.reading_links),
            ]
        )
        if not is_glm52_coding_breakthrough(text):
            continue
        event.category = "大模型动态"
        event.ai_title = "GLM-5.2长程编程超GPT-5.5，逼近Opus 4.8"
        event.one_sentence_summary = (
            "在 FrontierSWE 等长程编程基准中，GLM-5.2 仅落后 Opus 4.8 约 1%，"
            "超过 GPT-5.5 和 Opus 4.7，成为最高排名开源模型。"
        )
        event.detailed_summary = (
            "这条新闻的核心不是 GLM-5.2 又发布了一个模型，而是国产开源模型在长程编程和复杂工程任务上开始进入闭源旗舰第一梯队。"
            "对公众号选题来说，重点应放在开源模型对 Claude Code、Codex 类开发工作流和企业私有化部署成本的冲击。"
        )
        event.key_points = [
            "FrontierSWE 中 GLM-5.2 仅落后 Opus 4.8 约 1%，同时超过 GPT-5.5 和 Opus 4.7。",
            "PostTrainBench 等长程任务显示其已成为最高排名开源模型。",
            "1M 上下文和长程 Coding Agent 训练，提升复杂工程任务的连续执行能力。",
        ]
        event.why_it_matters = "国产开源模型开始进入 AI 编程第一梯队，可能改变开发者工具、企业私有化部署和模型成本竞争。"
        event.impact_analysis = {
            "technology": "长上下文、智能体编程和复杂工程任务能力成为模型竞争关键。",
            "business": "若真实工程表现稳定，企业可能用开源模型替代部分昂贵闭源编程模型。",
            "policy": "",
            "finance": "",
        }
        event.topic_angle = "从国产开源模型进入编程第一梯队解读：GLM-5.2超GPT-5.5逼近Opus"
        event.avoid_angle = "避免只写跑分胜负，重点复核榜单口径、测试场景、开源协议和真实工程可用性。"
        event.recommended = True
        event.priority_score = max(event.priority_score, 95.0)
        updated += 1
    return updated


def is_glm52_coding_breakthrough(text: str) -> bool:
    lowered = text.lower()
    if not ("glm-5.2" in lowered or "glm 5.2" in lowered or "glm5.2" in lowered):
        return False
    benchmark_terms = [
        "frontierswe",
        "posttrainbench",
        "swe-marathon",
        "code arena",
        "opus 4.7",
        "opus 4.8",
        "gpt-5.5",
        "编程第一",
        "全球可用模型第一",
        "最高排名开源模型",
    ]
    coding_terms = ["coding", "code", "swe", "编程", "工程任务", "coding agent"]
    return any(term in lowered for term in benchmark_terms) and any(term in lowered for term in coding_terms)


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
                "reading_links": [asdict(link) for link in event.reading_links],
            }
        )
    return topics


def enrich_event_reading_links(events: list[EventCard], analyses: list[ArticleAnalysis], *, max_links: int = 4) -> int:
    added = 0
    analyses_by_score = sorted(analyses, key=lambda item: item.priority_score, reverse=True)
    for event in events:
        seen_urls = {link.url for link in event.reading_links}
        seen_sources = {link.source_id for link in event.reading_links}
        next_order = len(event.reading_links) + 1
        for analysis in analyses_by_score:
            if len(event.reading_links) >= max_links:
                break
            if analysis.candidate.url in seen_urls or analysis.candidate.source_id in seen_sources:
                continue
            if not should_attach_supporting_link(event, analysis):
                continue
            event.reading_links.append(
                ReadingLink(
                    source_id=analysis.candidate.source_id,
                    source_name=analysis.candidate.source_name,
                    source_type=analysis.candidate.source_type,
                    source_role="related",
                    original_title=analysis.candidate.title,
                    url=analysis.candidate.url,
                    published_at=analysis.candidate.published_at,
                    link_label=analysis.candidate.source_name,
                    is_primary_reading_link=False,
                    display_order=next_order,
                )
            )
            seen_urls.add(analysis.candidate.url)
            seen_sources.add(analysis.candidate.source_id)
            next_order += 1
            added += 1
        event.source_count = len({link.source_id for link in event.reading_links})
        event.source_types = sorted({link.source_type for link in event.reading_links})
    return added


def should_attach_supporting_link(event: EventCard, analysis: ArticleAnalysis) -> bool:
    if event.category != analysis.category:
        return False
    event_text = event_relation_text(event)
    analysis_text = analysis_merge_text(analysis)
    event_is_glm52 = is_glm52_coding_breakthrough(event_text)
    analysis_is_glm52 = is_glm52_coding_breakthrough(analysis_text)
    if event_is_glm52 or analysis_is_glm52:
        return event_is_glm52 and analysis_is_glm52
    if normalized_model_versions(event_text) & normalized_model_versions(analysis_text):
        return True
    event_title = normalize_title(event.ai_title)
    analysis_title = normalize_title(analysis.ai_title or analysis.candidate.title)
    title_similarity = SequenceMatcher(None, event_title, analysis_title).ratio() if event_title and analysis_title else 0.0
    event_terms = title_terms(event_text)
    analysis_terms = title_terms(analysis_text)
    if not event_terms or not analysis_terms:
        return False
    shared = event_terms & analysis_terms
    return title_similarity >= 0.72 and count_strong_named_entities(shared) >= 1


def event_relation_text(event: EventCard) -> str:
    return " ".join(
        [
            event.ai_title,
            event.one_sentence_summary,
            event.detailed_summary,
            event.topic_angle,
            " ".join(event.key_points),
            " ".join(link.original_title for link in event.reading_links),
        ]
    )


def normalized_model_versions(text: str) -> set[str]:
    lowered = text.lower()
    versions = set()
    for match in re.finditer(r"\b([a-z]{2,})[- ]?(\d+(?:\.\d+)+)\b", lowered):
        prefix, version = match.groups()
        if prefix in MODEL_VERSION_PREFIXES:
            versions.add(f"{prefix}-{version}")
    return versions


def has_named_entity_overlap(terms: set[str]) -> bool:
    return any(re.search(r"[a-z]", term) and len(term) >= 4 for term in terms)


def count_strong_named_entities(terms: set[str]) -> int:
    generic = {
        "ai",
        "agent",
        "agents",
        "model",
        "models",
        "language",
        "benchmark",
        "benchmarks",
        "framework",
        "learning",
        "research",
        "data",
        "using",
        "based",
        "智能体",
        "模型",
        "语言",
        "基准",
        "研究",
        "数据",
        "学习",
        "能力",
    }
    return sum(1 for term in terms if term not in generic and re.search(r"[a-z]", term) and len(term) >= 4)


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
    left_ai_title = normalize_title(left.ai_title)
    right_ai_title = normalize_title(right.ai_title)
    if left_ai_title and right_ai_title:
        if left_ai_title == right_ai_title:
            return True
        if SequenceMatcher(None, left_ai_title, right_ai_title).ratio() >= 0.86:
            return True
    if is_glm52_coding_breakthrough(analysis_merge_text(left)) and is_glm52_coding_breakthrough(analysis_merge_text(right)):
        return True
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


def analysis_merge_text(analysis: ArticleAnalysis) -> str:
    return " ".join(
        [
            analysis.candidate.title,
            analysis.candidate.summary or "",
            analysis.ai_title,
            analysis.one_sentence_summary,
            analysis.detailed_summary,
        ]
    )


def keyword_overlap(left: str, right: str) -> float:
    left_terms = title_terms(left)
    right_terms = title_terms(right)
    if not left_terms or not right_terms:
        return 0.0
    return len(left_terms & right_terms) / len(left_terms | right_terms)


def title_terms(title: str) -> set[str]:
    terms = set(re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}|[\u4e00-\u9fff]{2,}", title))
    stop = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "this",
        "that",
        "new",
        "news",
        "how",
        "why",
        "what",
        "using",
        "based",
        "model",
        "models",
        "agent",
        "agents",
        "language",
        "benchmark",
        "framework",
        "learning",
        "research",
        "data",
        "发布",
        "推出",
        "最新",
        "模型",
        "智能体",
        "语言",
        "研究",
        "基准",
        "数据",
        "学习",
        "能力",
        "应用",
    }
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
