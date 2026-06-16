from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any


@dataclass(frozen=True)
class ArticleCandidate:
    source_id: str
    source_name: str
    source_type: str
    category_hint: str
    title: str
    url: str
    published_at: str | None = None
    summary: str | None = None
    language: str = "zh"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def with_url(self, url: str) -> "ArticleCandidate":
        return replace(self, url=url)

