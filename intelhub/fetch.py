from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html.parser import HTMLParser

from .config import Source
from .dedupe import canonicalize_url
from .models import ArticleCandidate


USER_AGENT = "AIIntelBot/0.1 (+personal research dashboard)"


@dataclass(frozen=True)
class FetchResult:
    source: Source
    candidates: list[ArticleCandidate]
    error: str | None = None


def fetch_source(source: Source, *, limit: int = 10) -> FetchResult:
    if source.method == "manual_link":
        return FetchResult(source=source, candidates=[])
    if not source.url:
        return FetchResult(source=source, candidates=[], error="source url is empty")
    try:
        if source.method in {"rss", "rsshub"}:
            candidates = fetch_rss(source, limit=limit)
        elif source.method in {"crawl", "sitemap", "playwright"}:
            candidates = fetch_links(source, limit=limit)
        else:
            candidates = []
    except Exception as exc:
        return FetchResult(source=source, candidates=[], error=str(exc))
    return FetchResult(source=source, candidates=candidates)


def fetch_rss(source: Source, *, limit: int = 10) -> list[ArticleCandidate]:
    body = http_get(source.url or "")
    root = ET.fromstring(body)
    candidates: list[ArticleCandidate] = []

    for item in root.findall(".//item"):
        title = _node_text(item, "title")
        link = _node_text(item, "link") or _node_text(item, "guid")
        published = _node_text(item, "pubDate")
        summary = _node_text(item, "description")
        if title and link:
            candidates.append(_candidate(source, title, link, published, summary))
        if len(candidates) >= limit:
            return candidates

    atom_ns = "{http://www.w3.org/2005/Atom}"
    for entry in root.findall(f".//{atom_ns}entry"):
        title = _node_text(entry, f"{atom_ns}title")
        published = _node_text(entry, f"{atom_ns}published") or _node_text(entry, f"{atom_ns}updated")
        summary = _node_text(entry, f"{atom_ns}summary")
        link = None
        for link_node in entry.findall(f"{atom_ns}link"):
            href = link_node.attrib.get("href")
            rel = link_node.attrib.get("rel", "alternate")
            if href and rel == "alternate":
                link = href
                break
        if title and link:
            candidates.append(_candidate(source, title, link, published, summary))
        if len(candidates) >= limit:
            break
    return candidates


def fetch_links(source: Source, *, limit: int = 10) -> list[ArticleCandidate]:
    body = http_get(source.url or "")
    parser = LinkParser(source.url or "")
    parser.feed(body.decode("utf-8", errors="replace"))
    candidates: list[ArticleCandidate] = []
    seen: set[str] = set()
    for link in parser.links:
        if not is_article_like(link.href, source.url or ""):
            continue
        key = canonicalize_url(link.href)
        if key in seen:
            continue
        seen.add(key)
        title = normalize_link_text(link.text)
        if not title:
            continue
        candidates.append(_candidate(source, title, key, None, None))
        if len(candidates) >= limit:
            break
    return candidates


def http_get(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/rss+xml,application/atom+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read()


def _candidate(source: Source, title: str, url: str, published_at: str | None, summary: str | None) -> ArticleCandidate:
    return ArticleCandidate(
        source_id=source.id,
        source_name=source.name,
        source_type=source.source_type,
        category_hint=source.category_hint,
        title=html.unescape(re.sub(r"\s+", " ", title)).strip(),
        url=canonicalize_url(url),
        published_at=published_at,
        summary=html.unescape(re.sub(r"\s+", " ", summary or "")).strip() or None,
        language=source.language,
    )


def _node_text(node: ET.Element, name: str) -> str | None:
    child = node.find(name)
    if child is None or child.text is None:
        return None
    return child.text.strip()


@dataclass(frozen=True)
class ParsedLink:
    href: str
    text: str


class LinkParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.links: list[ParsedLink] = []
        self._href: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attrs_dict = dict(attrs)
        href = attrs_dict.get("href")
        if not href:
            return
        self._href = urllib.parse.urljoin(self.base_url, href)
        self._parts = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or not self._href:
            return
        text = normalize_link_text(" ".join(self._parts))
        if text:
            self.links.append(ParsedLink(href=self._href, text=text))
        self._href = None
        self._parts = []


def normalize_link_text(text: str) -> str:
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) < 6:
        return ""
    return text[:220]


def is_article_like(url: str, source_url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    source = urllib.parse.urlparse(source_url)
    if parsed.scheme not in {"http", "https"}:
        return False
    if source.netloc and parsed.netloc != source.netloc:
        return False
    path = parsed.path.rstrip("/")
    if not path or path == urllib.parse.urlparse(source_url).path.rstrip("/"):
        return False
    blocked = ("/tag/", "/tags/", "/category/", "/author/", "/about", "/contact", "/login", "/privacy")
    if any(part in path.lower() for part in blocked):
        return False
    return True

