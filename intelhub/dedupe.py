from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

from .models import ArticleCandidate


def canonicalize_url(url: str) -> str:
    url = url.strip()
    url = re.sub(r"#.*$", "", url)
    url = re.sub(r"([?&])(utm_[^=&]+|spm|from|share_token)=[^&]*", r"\1", url)
    url = re.sub(r"[?&]+$", "", url)
    return url


def normalize_title(title: str) -> str:
    text = title.lower().strip()
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[^\w\u4e00-\u9fff]+", "", text)
    return text


def text_hash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def dedupe_candidates(candidates: Iterable[ArticleCandidate]) -> list[ArticleCandidate]:
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    unique: list[ArticleCandidate] = []
    for candidate in candidates:
        url_key = canonicalize_url(candidate.url)
        title_key = normalize_title(candidate.title)
        if url_key in seen_urls:
            continue
        if title_key and title_key in seen_titles:
            continue
        seen_urls.add(url_key)
        if title_key:
            seen_titles.add(title_key)
        unique.append(candidate.with_url(url_key))
    return unique

