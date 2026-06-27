from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ParsedArticle:
    title: str
    url: str
    source: str
    published_at: Optional[str]
    summary_raw: str


def article_to_json_dict(article: ParsedArticle) -> dict[str, Optional[str]]:
    return {
        "title": article.title,
        "url": article.url,
        "source": article.source,
        "published_at": article.published_at,
        "summary_raw": article.summary_raw,
    }
