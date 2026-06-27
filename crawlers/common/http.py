from __future__ import annotations

import logging
import time
from typing import Optional

import requests


def create_session(headers: dict[str, str] | None = None) -> requests.Session:
    session = requests.Session()
    if headers:
        session.headers.update(headers)
    return session


def fetch_html(
    session: requests.Session,
    url: str,
    timeout: int = 25,
    retries: int = 1,
    delay_seconds: float = 0.0,
    **kwargs: object,
) -> str:
    last_exc: Optional[Exception] = None

    for attempt in range(1, retries + 1):
        try:
            response = session.get(url, timeout=timeout, **kwargs)
            response.raise_for_status()

            if not response.encoding or response.encoding.lower() == "iso-8859-1":
                response.encoding = response.apparent_encoding

            return response.text
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < retries:
                logging.warning(
                    "Fetch failed attempt %s/%s for %s: %s",
                    attempt,
                    retries,
                    url,
                    exc,
                )
                if delay_seconds:
                    time.sleep(delay_seconds)

    raise last_exc or RuntimeError(f"Failed to fetch {url}")
