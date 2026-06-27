from __future__ import annotations

import re
from typing import Any


HTML_TAG_PATTERN = re.compile(r"<[^>]+>")


def clean_text(text: Any) -> str:
    if text is None:
        return ""

    normalized = str(text).replace("\xa0", " ")
    normalized = HTML_TAG_PATTERN.sub(" ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def normalize_for_search(text: Any) -> str:
    return clean_text(text).lower()
