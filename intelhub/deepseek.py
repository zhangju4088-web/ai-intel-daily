from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-pro"


def load_env_file(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class DeepSeekSettings:
    api_key: str
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL

    @classmethod
    def from_env(cls) -> "DeepSeekSettings":
        api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is empty")
        return cls(
            api_key=api_key,
            base_url=os.getenv("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
            model=os.getenv("DEEPSEEK_MODEL", DEFAULT_MODEL),
        )


class DeepSeekClient:
    def __init__(self, settings: DeepSeekSettings) -> None:
        self.settings = settings

    def complete_json(self, system: str, user: str, *, thinking: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "thinking": {"type": "enabled" if thinking else "disabled"},
            "temperature": 0.2,
            "max_tokens": 1800,
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        if thinking:
            payload["reasoning_effort"] = "medium"

        request = urllib.request.Request(
            f"{self.settings.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.settings.api_key}",
                "Accept": "application/json",
                "Connection": "close",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=75) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"DeepSeek request failed: {exc.code} {detail}") from exc

        content = data["choices"][0]["message"]["content"]
        return parse_json_object(content)


def parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    match = re.search(r"\{[\s\S]*\}", stripped)
    if not match:
        raise ValueError("model did not return a JSON object")
    parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("model JSON is not an object")
    return parsed


def build_article_summary_prompt(
    *,
    source_name: str,
    source_type: str,
    original_title: str,
    canonical_url: str,
    published_at: str | None,
    current_date: str,
    extracted_text: str,
) -> tuple[str, str]:
    system = """
你是一个服务 AI 垂直公众号博主的情报分析助手。你的任务是阅读公开文章正文，提取事实、判断价值、生成适合编辑快速决策的中文摘要。

要求：
1. 只基于正文和元数据，不编造正文没有的信息。
2. 明确区分“事实”和“你的分析判断”。
3. 保留关键公司、人物、国家、日期、金额、模型名称、政策名称、机构名称。
4. 不输出大段原文，不模仿原文表达，不洗稿。
5. 如果正文信息不足，请在 unknowns 中说明。
6. 输出必须是合法 JSON，不要输出 Markdown。
""".strip()
    user = f"""
请阅读以下文章，生成中文结构化情报。

元数据：
- 来源名称：{source_name}
- 来源类型：{source_type}
- 原始标题：{original_title}
- 原文链接：{canonical_url}
- 发布时间：{published_at or "未知"}
- 当前日期：{current_date}

正文：
{extracted_text[:6000]}

请输出 JSON：
{{
  "ai_title": "不超过32个中文字符，适合公众号编辑快速判断",
  "category": "大模型动态 | AI行业资讯 | 国际形势影响 | 国际金融",
  "one_sentence_summary": "不超过60个中文字符",
  "detailed_summary": "200-400字中文摘要",
  "key_points": ["3-5条要点"],
  "facts": ["正文明确陈述的关键事实"],
  "analysis": "你的分析判断，不能当事实写",
  "why_it_matters": "为什么重要",
  "impact_analysis": {{
    "technology": "技术影响，没有则写空字符串",
    "business": "商业影响，没有则写空字符串",
    "policy": "政策/国际关系影响，没有则写空字符串",
    "finance": "金融市场影响，没有则写空字符串"
  }},
  "topic_angle": "适合公众号写作的选题角度",
  "avoid_angle": "容易同质化或不建议采用的角度",
  "recommended": true,
  "priority_score": 0,
  "confidence": 0.0,
  "unknowns": ["正文没有确认但值得跟进的信息"]
}}
""".strip()
    return system, user
