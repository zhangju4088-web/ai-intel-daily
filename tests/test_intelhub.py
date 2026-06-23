from __future__ import annotations

import unittest
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

from intelhub.config import Source, load_sources
from intelhub.models import ArticleCandidate
from intelhub.fetch import is_navigation_text
from intelhub.pipeline import (
    apply_special_event_card_framing,
    build_topic_pool,
    choose_extraction_indexes,
    enrich_event_reading_links,
    local_analysis,
    merge_analyses,
)
from intelhub.render import render_digest_html
from intelhub.scoring import priority_score_breakdown, rough_priority_score
from intelhub.site import publish_static_site


class IntelHubTest(unittest.TestCase):
    def test_merge_same_event_keeps_multiple_reading_links(self) -> None:
        official = ArticleCandidate(
            source_id="openai_news",
            source_name="OpenAI News",
            source_type="official",
            category_hint="大模型动态",
            title="OpenAI launches new partner network for enterprise AI",
            url="https://openai.com/example",
            summary="OpenAI launches a partner network for enterprise AI adoption.",
            language="en",
        )
        wechat = ArticleCandidate(
            source_id="wx_qbitai",
            source_name="量子位",
            source_type="wechat",
            category_hint="大模型动态",
            title="OpenAI launches new partner network for enterprise AI",
            url="https://mp.weixin.qq.com/s/example",
            summary="量子位解读 OpenAI 企业 AI 伙伴网络。",
            language="zh",
        )

        events = merge_analyses(
            [local_analysis(official, None), local_analysis(wechat, None)],
            digest_date=date(2026, 6, 15),
        )

        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.source_count, 2)
        self.assertEqual(len(event.reading_links), 2)
        self.assertEqual(event.reading_links[0].source_type, "official")
        self.assertTrue(event.reading_links[0].is_primary_reading_link)
        self.assertEqual({link.source_type for link in event.reading_links}, {"official", "wechat"})

    def test_source_from_mapping_defaults(self) -> None:
        source = Source.from_mapping(
            {
                "id": "wx_example",
                "name": "示例公众号",
                "source_type": "wechat",
                "method": "manual_link",
            }
        )

        self.assertEqual(source.category_hint, "auto")
        self.assertEqual(source.language, "zh")
        self.assertTrue(source.enabled)

    def test_load_sources_includes_blog_and_social_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "sources.yaml"
            config_path.write_text(
                """
sources:
  - id: official
    name: Official
    source_type: official
    method: rss
    url: https://example.com/feed.xml
blog_sources:
  - id: blog
    name: Blog
    source_type: blog
    method: crawl
    url: https://example.com/blog
social_sources:
  - id: x_openai
    name: X OpenAI
    source_type: social
    method: rsshub
    url: ${RSSHUB_BASE_URL}/x/user/OpenAI
wechat_sources:
  - id: wx
    name: WeChat
    source_type: wechat
    method: manual_link
""",
                encoding="utf-8",
            )

            with patch.dict("os.environ", {}, clear=True):
                config = load_sources(config_path)

        source_ids = {source.id for source in config.sources}
        self.assertEqual(source_ids, {"official", "blog", "x_openai", "wx"})
        x_source = next(source for source in config.sources if source.id == "x_openai")
        self.assertFalse(x_source.enabled)
        self.assertIsNone(x_source.url)

    def test_static_site_archive_keeps_latest_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            site_dir = Path(tmp)
            publish_static_site(sample_digest("2026-06-14", 4), site_dir)
            publish_static_site(sample_digest("2026-06-15", 6), site_dir)

            self.assertTrue((site_dir / "index.html").exists())
            self.assertTrue((site_dir / "daily-digest.json").exists())
            self.assertTrue((site_dir / "archive" / "2026-06-14" / "index.html").exists())
            self.assertTrue((site_dir / "archive" / "2026-06-15" / "index.html").exists())

            archive_json = (site_dir / "archive" / "index.json").read_text(encoding="utf-8")
            self.assertLess(archive_json.find("2026-06-15"), archive_json.find("2026-06-14"))
            old_archive_html = (site_dir / "archive" / "2026-06-14" / "index.html").read_text(encoding="utf-8")
            self.assertIn('id="dateSelect"', old_archive_html)
            self.assertIn("2026-06-15", old_archive_html)
            self.assertNotIn(">归档</button>", old_archive_html)

    def test_render_uses_date_picker_instead_of_archive_tab(self) -> None:
        digest = sample_digest("2026-06-18", 1)
        digest["archive_entries"] = [
            {"date": "2026-06-18", "url": "archive/2026-06-18/", "selected_event_count": 1},
            {"date": "2026-06-17", "url": "archive/2026-06-17/", "selected_event_count": 1},
        ]

        rendered = render_digest_html(digest)

        self.assertIn('id="dateSelect"', rendered)
        self.assertIn("2026-06-17", rendered)
        self.assertNotIn('data-view="archive"', rendered)
        self.assertNotIn(">归档</button>", rendered)

    def test_render_includes_refresh_button(self) -> None:
        rendered = render_digest_html(sample_digest("2026-06-18", 1))

        self.assertIn('id="refreshButton"', rendered)
        self.assertIn("即时抓取", rendered)
        self.assertIn("actions/workflows/pages-digest.yml", rendered)

    def test_render_auth_config_from_environment(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "SITE_AUTH_USERNAME": "admin",
                "SITE_AUTH_PASSWORD_SHA256": "abc123",
                "SITE_REFRESH_WEBHOOK_URL": "https://refresh.example.com/run",
            },
        ):
            rendered = render_digest_html(sample_digest("2026-06-18", 1))

        self.assertIn('"enabled": true', rendered)
        self.assertIn('"username": "admin"', rendered)
        self.assertIn('"password_sha256": "abc123"', rendered)
        self.assertIn("https://refresh.example.com/run", rendered)

    def test_render_api_auth_user_management_controls(self) -> None:
        with patch.dict("os.environ", {"SITE_AUTH_API_URL": "https://auth.example.com"}):
            rendered = render_digest_html(sample_digest("2026-06-18", 1))

        self.assertIn('"mode": "api"', rendered)
        self.assertIn('"api_url": "https://auth.example.com"', rendered)
        self.assertIn('id="adminUsersButton"', rendered)
        self.assertIn("用户管理", rendered)
        self.assertIn('id="passwordForm"', rendered)
        self.assertIn("修改密码", rendered)
        self.assertIn("/admin/users", rendered)
        self.assertIn("/password", rendered)

    def test_fetch_filters_navigation_text(self) -> None:
        self.assertTrue(is_navigation_text("Subscribe to RSS"))
        self.assertTrue(is_navigation_text("Back to Home"))
        self.assertTrue(is_navigation_text("Calendar"))
        self.assertFalse(is_navigation_text("Federal Reserve issues FOMC statement"))

    def test_extraction_indexes_cover_finance(self) -> None:
        candidates = [
            ArticleCandidate(
                source_id=f"ai_{index}",
                source_name="AI Source",
                source_type="media",
                category_hint="大模型动态",
                title=f"OpenAI model update {index}",
                url=f"https://example.com/ai/{index}",
                summary=None,
                language="en",
            )
            for index in range(8)
        ]
        candidates.extend(
            ArticleCandidate(
                source_id=f"finance_{index}",
                source_name="Finance Source",
                source_type="finance",
                category_hint="国际金融",
                title=f"Federal Reserve rate signal {index}",
                url=f"https://example.com/finance/{index}",
                summary=None,
                language="en",
            )
            for index in range(4)
        )

        selected = choose_extraction_indexes(candidates, 4)

        self.assertTrue(any(candidates[index].category_hint == "国际金融" for index in selected))

    def test_hot_model_release_gets_domestic_model_boost(self) -> None:
        glm = ArticleCandidate(
            source_id="huggingface_blog",
            source_name="Hugging Face Blog",
            source_type="research",
            category_hint="大模型动态",
            title="GLM-5.2: Built for Long-Horizon Tasks",
            url="https://huggingface.co/blog/zai-org/glm-52-blog",
            summary=None,
            language="en",
        )
        generic = ArticleCandidate(
            source_id="huggingface_blog",
            source_name="Hugging Face Blog",
            source_type="research",
            category_hint="大模型动态",
            title="Language-guided 3D motion forecasting",
            url="https://example.com/research",
            summary=None,
            language="en",
        )

        self.assertGreater(rough_priority_score(glm), rough_priority_score(generic) + 15)

    def test_hot_model_release_still_ranks_high_without_timestamp(self) -> None:
        candidate = ArticleCandidate(
            source_id="qbitai_site",
            source_name="量子位",
            source_type="media",
            category_hint="AI行业资讯",
            title="智谱开源GLM-5.2登顶AI编程榜首",
            url="https://www.qbitai.com/2026/06/436085.html",
            summary=None,
            language="zh",
        )

        self.assertGreaterEqual(rough_priority_score(candidate), 75)

    def test_glm52_coding_breakthrough_gets_topic_framing(self) -> None:
        candidate = ArticleCandidate(
            source_id="huggingface_blog",
            source_name="Hugging Face Blog",
            source_type="research",
            category_hint="大模型动态",
            title="GLM-5.2: Built for Long-Horizon Tasks",
            url="https://huggingface.co/blog/zai-org/glm-52-blog",
            summary=None,
            language="en",
        )
        extracted_text = (
            "On FrontierSWE, GLM-5.2 trails Opus 4.8 by only 1%, "
            "while edging out GPT-5.5 by 1% and Opus 4.7 by 11%. "
            "Across long-horizon coding benchmarks, GLM-5.2 is the "
            "highest-ranked open-source model."
        )

        analysis = local_analysis(candidate, extracted_text)

        self.assertIn("GPT-5.5", analysis.ai_title)
        self.assertIn("逼近Opus", analysis.ai_title)
        self.assertIn("最高排名开源模型", analysis.one_sentence_summary)

    def test_glm52_coding_breakthrough_merges_multiple_sources(self) -> None:
        huggingface = ArticleCandidate(
            source_id="huggingface_blog",
            source_name="Hugging Face Blog",
            source_type="research",
            category_hint="大模型动态",
            title="GLM-5.2: Built for Long-Horizon Tasks",
            url="https://huggingface.co/blog/zai-org/glm-52-blog",
            summary=(
                "On FrontierSWE, GLM-5.2 trails Opus 4.8 by only 1%, "
                "while edging out GPT-5.5 and Opus 4.7."
            ),
            language="en",
        )
        qbitai = ArticleCandidate(
            source_id="qbitai_site",
            source_name="量子位",
            source_type="media",
            category_hint="AI行业资讯",
            title="刚刚，Fable-5之下，智谱开源的GLM-5.2拿下AI编程第一！",
            url="https://www.qbitai.com/2026/06/436085.html",
            summary="GLM-5.2 在 AI 编程榜单中表现突出，接近 Claude Opus 4.8，超过 GPT-5.5。",
            language="zh",
        )

        events = merge_analyses(
            [local_analysis(huggingface, None), local_analysis(qbitai, None)],
            digest_date=date(2026, 6, 18),
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].source_count, 2)
        self.assertEqual(len(events[0].reading_links), 2)

    def test_supporting_links_are_added_to_related_event(self) -> None:
        primary = ArticleCandidate(
            source_id="openai_news",
            source_name="OpenAI News",
            source_type="official",
            category_hint="大模型动态",
            title="OpenAI releases GPT-5.5 coding benchmark results",
            url="https://openai.com/gpt-55-coding",
            summary="GPT-5.5 improves coding benchmark results.",
            language="en",
        )
        supporting = ArticleCandidate(
            source_id="techcrunch_ai",
            source_name="TechCrunch AI",
            source_type="media",
            category_hint="大模型动态",
            title="GPT-5.5 coding benchmarks show OpenAI gains",
            url="https://techcrunch.com/gpt-55-coding",
            summary="Coverage of GPT-5.5 coding benchmarks and developer impact.",
            language="en",
        )
        analyses = [local_analysis(primary, None), local_analysis(supporting, None)]
        events = merge_analyses([analyses[0]], digest_date=date(2026, 6, 18))

        added = enrich_event_reading_links(events, analyses)

        self.assertEqual(added, 1)
        self.assertEqual(events[0].source_count, 2)
        self.assertEqual(len(events[0].reading_links), 2)

    def test_topic_pool_carries_tags_sources_and_recommendation_reason(self) -> None:
        primary = ArticleCandidate(
            source_id="openai_news",
            source_name="OpenAI News",
            source_type="official",
            category_hint="大模型动态",
            title="OpenAI launches new coding agent benchmark",
            url="https://openai.com/benchmark",
            summary="OpenAI launches a new coding benchmark for agentic software development.",
            language="en",
        )
        social = ArticleCandidate(
            source_id="hackernews_ai",
            source_name="Hacker News AI",
            source_type="social",
            category_hint="大模型动态",
            title="OpenAI launches new coding agent benchmark",
            url="https://news.ycombinator.com/item?id=1",
            summary="Developers discuss the OpenAI coding benchmark.",
            language="en",
        )
        events = merge_analyses(
            [local_analysis(primary, None), local_analysis(social, None)],
            digest_date=date(2026, 6, 23),
        )

        topics = build_topic_pool(events)

        self.assertGreaterEqual(events[0].source_count, 2)
        self.assertIn("编程工具", events[0].tags)
        self.assertIn("社区讨论", events[0].tags)
        self.assertGreater(events[0].signal_strength, 0)
        self.assertEqual(topics[0]["source_count"], 2)
        self.assertIn("recommendation_reason", topics[0])
        self.assertIn("reading_links", topics[0])

    def test_unrelated_research_is_not_added_as_supporting_link(self) -> None:
        glm = ArticleCandidate(
            source_id="huggingface_blog",
            source_name="Hugging Face Blog",
            source_type="research",
            category_hint="大模型动态",
            title="GLM-5.2: Built for Long-Horizon Tasks",
            url="https://huggingface.co/blog/zai-org/glm-52-blog",
            summary=(
                "On FrontierSWE, GLM-5.2 trails Opus 4.8 by only 1%, "
                "while edging out GPT-5.5 and Opus 4.7."
            ),
            language="en",
        )
        unrelated = ArticleCandidate(
            source_id="arxiv_cs_cl",
            source_name="arXiv cs.CL",
            source_type="research",
            category_hint="大模型动态",
            title="PromptMN: Pseudo Prompting Language",
            url="https://arxiv.org/abs/2606.00000",
            summary="A paper about pseudo prompting language methods.",
            language="en",
        )
        analyses = [local_analysis(glm, None), local_analysis(unrelated, None)]
        events = merge_analyses([analyses[0]], digest_date=date(2026, 6, 18))
        apply_special_event_card_framing(events)

        added = enrich_event_reading_links(events, analyses)

        self.assertEqual(added, 0)
        self.assertEqual(len(events[0].reading_links), 1)

    def test_topic_pool_carries_reading_links(self) -> None:
        candidate = ArticleCandidate(
            source_id="openai_news",
            source_name="OpenAI News",
            source_type="official",
            category_hint="大模型动态",
            title="OpenAI releases GPT-5.5 coding benchmark results",
            url="https://openai.com/gpt-55-coding",
            summary="GPT-5.5 improves coding benchmark results.",
            language="en",
        )
        events = merge_analyses([local_analysis(candidate, None)], digest_date=date(2026, 6, 18))

        topics = build_topic_pool(events)

        self.assertEqual(topics[0]["reading_links"][0]["url"], "https://openai.com/gpt-55-coding")

    def test_source_weight_affects_priority_score(self) -> None:
        title = "NVIDIA Blackwell benchmark shows stronger AI training performance"
        high_weight = ArticleCandidate(
            source_id="nvidia_blog",
            source_name="NVIDIA Blog",
            source_type="official",
            category_hint="AI行业资讯",
            title=title,
            url="https://example.com/high",
            source_weight=1.20,
            language="en",
        )
        low_weight = ArticleCandidate(
            source_id="generic_ai",
            source_name="Generic AI Site",
            source_type="official",
            category_hint="AI行业资讯",
            title=title,
            url="https://example.com/low",
            source_weight=0.80,
            language="en",
        )

        self.assertGreater(rough_priority_score(high_weight), rough_priority_score(low_weight))

    def test_finance_context_gets_category_boost(self) -> None:
        candidate = ArticleCandidate(
            source_id="fed",
            source_name="Federal Reserve",
            source_type="finance",
            category_hint="国际金融",
            title="Federal Reserve signals interest rate cuts as inflation cools",
            url="https://example.com/fed",
            language="en",
        )
        breakdown = priority_score_breakdown(candidate)

        self.assertGreaterEqual(breakdown["finance"], 10)
        self.assertGreaterEqual(breakdown["score"], 60)

    def test_low_value_promotional_items_are_penalized(self) -> None:
        candidate = ArticleCandidate(
            source_id="generic_ai",
            source_name="Generic AI Site",
            source_type="media",
            category_hint="AI行业资讯",
            title="Subscribe to our AI newsletter and webinar roundup",
            url="https://example.com/newsletter",
            language="en",
        )
        breakdown = priority_score_breakdown(candidate)

        self.assertLess(breakdown["low_value_penalty"], 0)
        self.assertLess(breakdown["score"], 45)

    def test_finance_short_terms_do_not_match_inside_other_words(self) -> None:
        candidate = ArticleCandidate(
            source_id="arxiv_cs_ai",
            source_name="arXiv cs.AI",
            source_type="research",
            category_hint="大模型动态",
            title="Federated learning benchmark for medical AI",
            url="https://example.com/federated-learning",
            language="en",
        )
        breakdown = priority_score_breakdown(candidate)

        self.assertEqual(breakdown["finance"], 0)

    def test_chip_export_controls_are_high_impact_geopolitics(self) -> None:
        candidate = ArticleCandidate(
            source_id="reuters_world",
            source_name="Reuters",
            source_type="media",
            category_hint="国际形势影响",
            title="U.S. expands AI chip export controls on China",
            url="https://example.com/export-controls",
            language="en",
        )
        breakdown = priority_score_breakdown(candidate)

        self.assertGreaterEqual(breakdown["geopolitical"], 10)
        self.assertGreaterEqual(breakdown["score"], 60)

def sample_digest(digest_date: str, selected_count: int) -> dict:
    return {
        "digest_date": digest_date,
        "generated_at": f"{digest_date}T00:00:00+00:00",
        "stats": {
            "fetched_candidate_count": selected_count,
            "unique_candidate_count": selected_count,
            "analysis_count": selected_count,
            "event_count": selected_count,
            "selected_event_count": selected_count,
            "fetch_error_count": 0,
        },
        "fetch_errors": [],
        "categories": {
            "大模型动态": [],
            "AI行业资讯": [],
            "国际形势影响": [],
            "国际金融": [],
        },
        "top10": [],
        "topic_pool": [],
    }


if __name__ == "__main__":
    unittest.main()
