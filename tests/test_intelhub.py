from __future__ import annotations

import unittest
import tempfile
from datetime import date
from pathlib import Path

from intelhub.config import Source
from intelhub.models import ArticleCandidate
from intelhub.fetch import is_navigation_text
from intelhub.pipeline import choose_extraction_indexes, local_analysis, merge_analyses
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
