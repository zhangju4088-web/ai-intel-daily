from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import Source
from .dedupe import canonicalize_url
from .models import ArticleCandidate


def append_manual_link(
    path: Path,
    *,
    source_id: str,
    title: str,
    url: str,
    published_at: str | None = None,
    summary: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "source_id": source_id,
        "title": title,
        "url": canonicalize_url(url),
        "published_at": published_at,
        "summary": summary,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_manual_candidates(path: Path, sources: dict[str, Source]) -> list[ArticleCandidate]:
    if not path.exists():
        return []
    candidates: list[ArticleCandidate] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL at {path}:{line_number}: {exc}") from exc
        candidates.append(_candidate_from_record(record, sources))
    return candidates


def _candidate_from_record(record: dict[str, Any], sources: dict[str, Source]) -> ArticleCandidate:
    source_id = str(record["source_id"])
    source = sources.get(source_id)
    if not source:
        raise ValueError(f"manual link references unknown source_id: {source_id}")
    return ArticleCandidate(
        source_id=source.id,
        source_name=source.name,
        source_type=source.source_type,
        category_hint=source.category_hint,
        title=str(record["title"]).strip(),
        url=canonicalize_url(str(record["url"])),
        published_at=record.get("published_at"),
        summary=record.get("summary"),
        language=source.language,
    )

