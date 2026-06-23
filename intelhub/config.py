from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    category_hint: str
    source_type: str
    method: str
    url: str | None = None
    account_id: str | None = None
    language: str = "zh"
    weight: float = 1.0
    enabled: bool = True
    notes: str | None = None

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "Source":
        url = _expand_env(_optional_str(data.get("url")))
        enabled = bool(data.get("enabled", True))
        if data.get("method") == "rsshub" and not url:
            enabled = False
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            category_hint=str(data.get("category_hint", "auto")),
            source_type=str(data.get("source_type", "other")),
            method=str(data.get("method", "crawl")),
            url=url,
            account_id=_optional_str(data.get("account_id")),
            language=str(data.get("language", "zh")),
            weight=float(data.get("weight", 1.0)),
            enabled=enabled,
            notes=_optional_str(data.get("notes")),
        )


@dataclass(frozen=True)
class SourceConfig:
    defaults: dict[str, Any]
    categories: list[str]
    sources: list[Source]

    def enabled_sources(self) -> list[Source]:
        return [source for source in self.sources if source.enabled]


def load_sources(path: Path) -> SourceConfig:
    data = _load_yaml(path)
    raw_sources = []
    for section in ("sources", "blog_sources", "social_sources", "wechat_sources"):
        raw_sources.extend(data.get(section, []))
    sources = [Source.from_mapping(item) for item in raw_sources]
    return SourceConfig(
        defaults=dict(data.get("defaults", {})),
        categories=[str(item) for item in data.get("categories", [])],
        sources=sources,
    )


def _load_yaml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
    except Exception:
        return _load_simple_yaml(text)

    parsed = yaml.safe_load(text)
    if not isinstance(parsed, dict):
        raise ValueError(f"config root must be a mapping: {path}")
    return parsed


def _load_simple_yaml(text: str) -> dict[str, Any]:
    """Parse the small YAML subset used by config/sources.yaml.

    PyYAML is preferred when installed. This fallback keeps the MVP commands
    runnable in a fresh standard-library-only Python environment.
    """

    result: dict[str, Any] = {}
    section: str | None = None
    current_item: dict[str, Any] | None = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith(" "):
            key = stripped.rstrip(":")
            section = key
            current_item = None
            if key in {"sources", "blog_sources", "social_sources", "wechat_sources", "categories"}:
                result[key] = []
            else:
                result[key] = {}
            continue
        if section is None:
            continue

        if section == "categories":
            if stripped.startswith("- "):
                result[section].append(stripped[2:].strip())
            continue

        if section in {"sources", "blog_sources", "social_sources", "wechat_sources"}:
            if stripped.startswith("- "):
                current_item = {}
                result[section].append(current_item)
                remainder = stripped[2:].strip()
                if remainder:
                    key, value = _split_key_value(remainder)
                    current_item[key] = _parse_scalar(value)
            elif current_item is not None and ":" in stripped:
                key, value = _split_key_value(stripped)
                current_item[key] = _parse_scalar(value)
            continue

        if isinstance(result.get(section), dict) and ":" in stripped:
            key, value = _split_key_value(stripped)
            result[section][key] = _parse_scalar(value)

    return result


def _split_key_value(text: str) -> tuple[str, str]:
    key, value = text.split(":", 1)
    return key.strip(), value.strip()


def _parse_scalar(value: str) -> Any:
    if value == "":
        return None
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value in {"null", "None", "~"}:
        return None
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _expand_env(value: str | None) -> str | None:
    if value is None:
        return None
    text = value
    for match in re_find_env_vars(text):
        replacement = os_env(match)
        if replacement is None:
            return None
        text = text.replace("${" + match + "}", replacement)
    return text or None


def re_find_env_vars(text: str) -> list[str]:
    import re

    return re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", text)


def os_env(name: str) -> str | None:
    import os

    return os.getenv(name)
