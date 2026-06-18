from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .pipeline import write_digest_json
from .render import render_archive_index, write_digest_html


def publish_static_site(digest: dict[str, Any], site_dir: Path) -> None:
    digest_date = str(digest["digest_date"])
    site_dir.mkdir(parents=True, exist_ok=True)

    archive_day_dir = site_dir / "archive" / digest_date
    archive_day_dir.mkdir(parents=True, exist_ok=True)

    entries = load_archive_entries(site_dir / "archive" / "index.json")
    entries = upsert_archive_entry(entries, digest)
    digest_with_archive = dict(digest)
    digest_with_archive["archive_entries"] = entries

    write_digest_json(digest_with_archive, site_dir / "daily-digest.json")
    write_digest_html(digest_with_archive, site_dir / "index.html")
    write_digest_json(digest_with_archive, archive_day_dir / "daily-digest.json")
    write_digest_html(digest_with_archive, archive_day_dir / "index.html")

    write_archive_entries(site_dir / "archive" / "index.json", entries)
    (site_dir / "archive" / "index.html").write_text(render_archive_index(entries), encoding="utf-8")
    refresh_archive_pages(site_dir, entries)


def load_archive_entries(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def write_archive_entries(path: Path, entries: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def refresh_archive_pages(site_dir: Path, entries: list[dict[str, Any]]) -> None:
    for entry in entries:
        digest_date = str(entry.get("date", "")).strip()
        if not digest_date:
            continue
        digest_path = site_dir / "archive" / digest_date / "daily-digest.json"
        if not digest_path.exists():
            continue
        try:
            digest = json.loads(digest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(digest, dict):
            continue
        digest["archive_entries"] = entries
        write_digest_json(digest, digest_path)
        write_digest_html(digest, site_dir / "archive" / digest_date / "index.html")


def upsert_archive_entry(entries: list[dict[str, Any]], digest: dict[str, Any]) -> list[dict[str, Any]]:
    digest_date = str(digest["digest_date"])
    stats = digest.get("stats", {})
    entry = {
        "date": digest_date,
        "generated_at": digest.get("generated_at"),
        "selected_event_count": stats.get("selected_event_count", 0),
        "event_count": stats.get("event_count", 0),
        "top10_count": len(digest.get("top10", [])),
        "url": f"archive/{digest_date}/",
        "json_url": f"archive/{digest_date}/daily-digest.json",
    }
    without_current = [item for item in entries if item.get("date") != digest_date]
    without_current.append(entry)
    return sorted(without_current, key=lambda item: str(item.get("date", "")), reverse=True)
