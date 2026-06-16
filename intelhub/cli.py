from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from .config import Source, load_sources
from .dedupe import dedupe_candidates
from .deepseek import DeepSeekClient, DeepSeekSettings, build_article_summary_prompt, load_env_file
from .extract import extract_url_text
from .fetch import fetch_source
from .manual import append_manual_link, load_manual_candidates
from .models import ArticleCandidate
from .pipeline import build_daily_digest, write_digest_json
from .render import write_digest_html
from .scoring import rough_priority_score
from .site import publish_static_site


DEFAULT_CONFIG = Path("config/sources.yaml")
DEFAULT_MANUAL_LINKS = Path("data/manual-links.jsonl")


def cmd_sources(args: argparse.Namespace) -> int:
    config = load_sources(args.config)
    sources = config.enabled_sources()
    method_counts = _count_by(sources, "method")
    type_counts = _count_by(sources, "source_type")
    print(f"enabled sources: {len(sources)}")
    print("by method:", json.dumps(method_counts, ensure_ascii=False, sort_keys=True))
    print("by source_type:", json.dumps(type_counts, ensure_ascii=False, sort_keys=True))
    if args.verbose:
        for source in sources:
            print(f"- {source.id} [{source.method}/{source.source_type}] {source.name}")
    return 0


def cmd_fetch_preview(args: argparse.Namespace) -> int:
    config = load_sources(args.config)
    sources = [source for source in config.enabled_sources() if source.method != "manual_link"]
    if args.source:
        sources = [source for source in sources if source.id in set(args.source)]
    if args.limit_sources is not None:
        sources = sources[: args.limit_sources]

    all_candidates: list[ArticleCandidate] = []
    errors: list[dict[str, str]] = []
    if args.manual_links:
        source_map = {source.id: source for source in config.enabled_sources()}
        manual_candidates = load_manual_candidates(args.manual_links, source_map)
        all_candidates.extend(manual_candidates)
        print(f"loaded {len(manual_candidates):>2} manual links", file=sys.stderr)

    for source in sources:
        result = fetch_source(source, limit=args.per_source)
        if result.error:
            errors.append({"source_id": source.id, "error": result.error})
            print(f"failed {source.id}: {result.error}", file=sys.stderr)
            continue
        all_candidates.extend(result.candidates)
        print(f"fetched {len(result.candidates):>2} from {source.id}", file=sys.stderr)

    unique = dedupe_candidates(all_candidates)
    rows = []
    for candidate in unique:
        item = candidate.as_dict()
        item["rough_priority_score"] = rough_priority_score(candidate)
        rows.append(item)
    rows.sort(key=lambda item: item["rough_priority_score"], reverse=True)

    output = {
        "candidate_count": len(all_candidates),
        "unique_count": len(rows),
        "error_count": len(errors),
        "errors": errors,
        "items": rows[: args.limit],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(output['items'])} preview items to {args.out}")
    return 0


def cmd_add_manual_link(args: argparse.Namespace) -> int:
    config = load_sources(args.config)
    source_ids = {source.id for source in config.enabled_sources()}
    if args.source_id not in source_ids:
        print(f"unknown source_id: {args.source_id}", file=sys.stderr)
        return 2
    append_manual_link(
        args.manual_links,
        source_id=args.source_id,
        title=args.title,
        url=args.url,
        published_at=args.published_at,
        summary=args.summary,
    )
    print(f"added manual link to {args.manual_links}")
    return 0


def cmd_extract_url(args: argparse.Namespace) -> int:
    try:
        text = extract_url_text(args.url)
    except Exception as exc:
        print(f"failed to extract url: {exc}", file=sys.stderr)
        return 1
    if args.max_chars:
        text = text[: args.max_chars]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(f"wrote extracted text to {args.out} ({len(text)} chars)")
    return 0


def cmd_summarize_file(args: argparse.Namespace) -> int:
    load_env_file()
    text = args.article.read_text(encoding="utf-8")
    client = DeepSeekClient(DeepSeekSettings.from_env())
    system, user = build_article_summary_prompt(
        source_name=args.source_name,
        source_type=args.source_type,
        original_title=args.title,
        canonical_url=args.url,
        published_at=args.published_at,
        current_date=args.current_date,
        extracted_text=text,
    )
    result = client.complete_json(system, user, thinking=args.thinking)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote summary to {args.out}")
    return 0


def cmd_daily(args: argparse.Namespace) -> int:
    load_env_file()
    if args.summarize_with == "deepseek" and not args.extract_text:
        print("--summarize-with deepseek requires --extract-text", file=sys.stderr)
        return 2
    digest = build_daily_digest(
        config_path=args.config,
        manual_links_path=args.manual_links,
        digest_date=args.date,
        source_ids=set(args.source) if args.source else None,
        limit_sources=args.limit_sources,
        per_source=args.per_source,
        top_per_category=args.top_per_category,
        extract_text=args.extract_text,
        extract_limit=args.extract_limit,
        summarize_with=args.summarize_with,
    )
    write_digest_json(digest, args.out_json)
    write_digest_html(digest, args.out_html)
    if args.site_dir:
        publish_static_site(digest, args.site_dir)
    stats = digest["stats"]
    print(
        "wrote daily digest "
        f"json={args.out_json} html={args.out_html} "
        f"events={stats['event_count']} selected={stats['selected_event_count']}"
    )
    if args.site_dir:
        print(f"updated static site at {args.site_dir}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI intelligence source collector MVP.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sources = subparsers.add_parser("sources", help="Inspect configured sources.")
    sources.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    sources.add_argument("--verbose", action="store_true")
    sources.set_defaults(func=cmd_sources)

    preview = subparsers.add_parser("fetch-preview", help="Fetch candidate links from configured sources.")
    preview.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    preview.add_argument("--source", action="append", help="Only fetch a source id; can be repeated.")
    preview.add_argument("--limit-sources", type=int, default=5)
    preview.add_argument("--per-source", type=int, default=5)
    preview.add_argument("--limit", type=int, default=30)
    preview.add_argument("--manual-links", type=Path, default=DEFAULT_MANUAL_LINKS)
    preview.add_argument("--out", type=Path, default=Path("outputs/intel-preview.json"))
    preview.set_defaults(func=cmd_fetch_preview)

    manual = subparsers.add_parser("add-manual-link", help="Append a public article link to the manual queue.")
    manual.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    manual.add_argument("--manual-links", type=Path, default=DEFAULT_MANUAL_LINKS)
    manual.add_argument("--source-id", required=True)
    manual.add_argument("--title", required=True)
    manual.add_argument("--url", required=True)
    manual.add_argument("--published-at")
    manual.add_argument("--summary")
    manual.set_defaults(func=cmd_add_manual_link)

    extract = subparsers.add_parser("extract-url", help="Extract readable text from a public URL.")
    extract.add_argument("url")
    extract.add_argument("--max-chars", type=int)
    extract.add_argument("--out", type=Path, default=Path("outputs/extracted-article.txt"))
    extract.set_defaults(func=cmd_extract_url)

    summarize = subparsers.add_parser("summarize-file", help="Summarize a local article text file with DeepSeek.")
    summarize.add_argument("article", type=Path)
    summarize.add_argument("--title", required=True)
    summarize.add_argument("--url", default="manual://local")
    summarize.add_argument("--source-name", default="手动输入")
    summarize.add_argument("--source-type", default="other")
    summarize.add_argument("--published-at")
    summarize.add_argument("--current-date", default="2026-06-15")
    summarize.add_argument("--thinking", action="store_true")
    summarize.add_argument("--out", type=Path, default=Path("outputs/intel-summary.json"))
    summarize.set_defaults(func=cmd_summarize_file)

    daily = subparsers.add_parser("daily", help="Build a local daily digest JSON and HTML file.")
    daily.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    daily.add_argument("--manual-links", type=Path, default=DEFAULT_MANUAL_LINKS)
    daily.add_argument("--source", action="append", help="Only fetch a source id; can be repeated.")
    daily.add_argument("--limit-sources", type=int, help="Limit number of web sources for local testing.")
    daily.add_argument("--per-source", type=int, default=5)
    daily.add_argument("--top-per-category", type=int, default=15)
    daily.add_argument("--extract-text", action="store_true", help="Extract article body text before summarizing.")
    daily.add_argument("--extract-limit", type=int, default=20)
    daily.add_argument("--summarize-with", choices=["local", "deepseek"], default="local")
    daily.add_argument("--date", type=_parse_date, default=date.today())
    daily.add_argument("--out-json", type=Path, default=Path("outputs/daily-digest.json"))
    daily.add_argument("--out-html", type=Path, default=Path("outputs/daily-digest.html"))
    daily.add_argument("--site-dir", type=Path, help="Also publish latest and dated archive pages into this static site directory.")
    daily.set_defaults(func=cmd_daily)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv or sys.argv[1:])
    return args.func(args)


def _count_by(sources: list[Source], attr: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for source in sources:
        value = str(getattr(source, attr))
        counts[value] = counts.get(value, 0) + 1
    return counts


def _parse_date(value: str):
    from datetime import date

    return date.fromisoformat(value)


if __name__ == "__main__":
    raise SystemExit(main())
