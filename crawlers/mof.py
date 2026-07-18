from __future__ import annotations

import argparse
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional
from urllib.parse import urljoin, urlparse, urlunparse
from zoneinfo import ZoneInfo

import requests

from crawlers.common.keywords import LEGAL_KEYWORDS, TOPIC_KEYWORDS

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

SOURCE_NAME = "Cổng thông tin điện tử Bộ Tài chính"
BASE_SITE_URL = "https://mof.gov.vn/"
LISTING_URL = "https://mof.gov.vn/api/article/reads"
LEGACY_ARTICLE_PATH = "webcenter/portal/btcvn/pages_r/l/tin-bo-tai-chinh"

DEFAULT_CATEGORY_IDS = [
    "f0d30405-0417-46a5-9dd0-fd1472428c57",
    "63661983-10cb-458c-b835-76d8c1276450",
    "38ccd03f-ccaf-4e4d-9319-b90df2207feb",
]
DEFAULT_ITEMS_PER_PAGE = 10

DATE_PATTERN = re.compile(
    r"\b(\d{2}/\d{2}/\d{4}|\d{2}-\d{2}-\d{4})(?:\s+(\d{2}:\d{2}(?::\d{2})?))?\b"
)

HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en,vi;q=0.9,en-US;q=0.8",
    "content-type": "application/json; charset=UTF-8",
    "origin": "https://mof.gov.vn",
    "referer": "https://mof.gov.vn/",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/148.0.0.0 Safari/537.36"
    ),
}

REQUEST_TIMEOUT = 25
POLITE_DELAY_SECONDS = 0.8


@dataclass
class ParsedArticle:
    title: str
    url: str
    source: str
    published_at: Optional[str]
    summary_raw: str
    category_url: str


def clean_text(text: Optional[Any]) -> str:
    if text is None:
        return ""
    text = str(text).replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_for_search(text: str) -> str:
    return clean_text(text).lower()


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(fragment=""))


def first_present(item: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


def try_parse_datetime(raw: Optional[Any]) -> Optional[datetime]:
    raw_text = clean_text(raw)
    if not raw_text:
        return None

    match = DATE_PATTERN.search(raw_text)
    if match:
        raw_text = match.group(1)
        if match.group(2):
            raw_text = f"{raw_text} {match.group(2)}"

    if raw_text.endswith("Z"):
        raw_text = raw_text[:-1] + "+0000"

    candidates = [
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y %H:%M",
        "%d-%m-%Y",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ]

    for fmt in candidates:
        try:
            dt = datetime.strptime(raw_text, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=VN_TZ)
            return dt.astimezone(VN_TZ)
        except ValueError:
            continue

    return None


def format_datetime(raw: Optional[Any]) -> Optional[str]:
    parsed = try_parse_datetime(raw)
    if not parsed:
        return None
    return parsed.strftime("%Y-%m-%d %H:%M")


def build_category_url(category_id: str) -> str:
    return f"{BASE_SITE_URL.rstrip('/')}/?categoryId={category_id}"


def build_article_url(item: dict[str, Any]) -> str:
    raw_url = clean_text(first_present(item, ["url", "link", "articleUrl", "href"]))
    if raw_url:
        return canonicalize_url(urljoin(BASE_SITE_URL, raw_url))

    slug = clean_text(first_present(item, ["slug", "articleSlug", "alias", "id"]))
    category_slug = clean_text(item.get("categorySlug"))
    root_category_slug = clean_text(item.get("rootCategorySlug"))

    if slug and category_slug and root_category_slug:
        return canonicalize_url(urljoin(BASE_SITE_URL, f"{root_category_slug}/{category_slug}/{slug}"))

    if slug and category_slug:
        return canonicalize_url(urljoin(BASE_SITE_URL, f"{category_slug}/{slug}"))

    if slug:
        return (
            f"{BASE_SITE_URL.rstrip('/')}/{LEGACY_ARTICLE_PATH}"
            f"?dDocName={slug}"
        )

    return BASE_SITE_URL


def extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if not isinstance(payload, dict):
        return []

    for key in ["data", "content", "items", "articles", "results"]:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    nested = payload.get("result")
    if isinstance(nested, dict):
        return extract_items(nested)

    return []


def extract_listing_articles(payload: Any, category_id: str) -> list[ParsedArticle]:
    articles: list[ParsedArticle] = []
    category_url = build_category_url(category_id)

    for item in extract_items(payload):
        title = clean_text(
            first_present(item, ["title", "name", "articleTitle", "displayTitle", "subject"])
        )
        if not title:
            continue

        published_at = format_datetime(
            first_present(
                item,
                [
                    "publicationTime",
                    "publishDate",
                    "publishTime",
                    "publishedAt",
                    "createdDate",
                    "createTime",
                    "date",
                ],
            )
        )
        summary = clean_text(
            first_present(item, ["description", "summary", "brief", "sapo", "introtext"])
        )

        articles.append(
            ParsedArticle(
                title=title,
                url=build_article_url(item),
                source=SOURCE_NAME,
                published_at=published_at,
                summary_raw=summary,
                category_url=category_url,
            )
        )

    return articles


def fetch_listing_page(
    session: requests.Session,
    category_id: str,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    response = session.post(
        LISTING_URL,
        params={"offset": offset, "limit": limit},
        json={"categoryId": category_id},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def keyword_hits(text: str, keywords: list[str]) -> list[str]:
    haystack = normalize_for_search(text)
    hits = []

    for keyword in keywords:
        kw = normalize_for_search(keyword)
        if kw and kw in haystack:
            hits.append(keyword)

    return sorted(set(hits))


def is_relevant_article(
    article: ParsedArticle,
    require_legal_keyword: bool = True,
    require_topic_keyword: bool = True,
) -> bool:
    searchable_text = " ".join([article.title, article.summary_raw])

    legal_hits = keyword_hits(searchable_text, LEGAL_KEYWORDS)
    topic_hits = keyword_hits(searchable_text, TOPIC_KEYWORDS)

    if require_legal_keyword and not legal_hits:
        return False

    if require_topic_keyword and not topic_hits:
        return False

    return True


def get_start_date(days: Optional[int], now: Optional[datetime] = None) -> Optional[datetime.date]:
    if days is None:
        return None

    current = now or datetime.now(VN_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=VN_TZ)

    day_count = max(days, 1)
    return (current.astimezone(VN_TZ) - timedelta(days=day_count - 1)).date()


def is_within_days(
    published_at: Optional[str],
    days: Optional[int],
    now: Optional[datetime] = None,
) -> bool:
    start_date = get_start_date(days, now=now)
    if start_date is None:
        return True

    if not published_at:
        return True

    parsed = try_parse_datetime(published_at)
    if not parsed:
        return True

    return parsed.date() >= start_date


def is_older_than_window(
    published_at: Optional[str],
    days: Optional[int],
    now: Optional[datetime] = None,
) -> bool:
    start_date = get_start_date(days, now=now)
    if start_date is None or not published_at:
        return False

    parsed = try_parse_datetime(published_at)
    if not parsed:
        return False

    return parsed.date() < start_date


def article_to_json_dict(article: ParsedArticle) -> dict:
    return {
        "title": article.title,
        "url": article.url,
        "source": article.source,
        "published_at": article.published_at,
        "summary_raw": article.summary_raw,
        "category_url": article.category_url,
    }


def parse_category_ids(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def crawl_mof(
    category_ids: Optional[list[str]] = None,
    days: Optional[int] = 1,
    max_articles: int = 50,
    items_per_page: int = DEFAULT_ITEMS_PER_PAGE,
    max_pages_per_category: int = 5,
    filter_relevant: bool = True,
    require_legal_keyword: bool = True,
    require_topic_keyword: bool = True,
    session: Optional[requests.Session] = None,
    now: Optional[datetime] = None,
) -> list[dict]:
    """
    Main function để đưa vào hệ thống.

    Returns:
        list[dict] theo format:
        {
          "title": "...",
          "url": "...",
          "source": "Cổng thông tin điện tử Bộ Tài chính",
          "published_at": "2026-07-10 18:12",
          "summary_raw": "...",
          "category_url": "https://mof.gov.vn/?categoryId=..."
        }
    """
    logging.info("Start crawling MOF article API")

    own_session = session is None
    session = session or requests.Session()
    session.headers.update(HEADERS)

    results: list[dict] = []
    seen_links: set[str] = set()

    try:
        for category_id in category_ids or DEFAULT_CATEGORY_IDS:
            logging.info("Start MOF category_id=%s", category_id)

            for page_no in range(max_pages_per_category):
                if len(results) >= max_articles:
                    break

                offset = page_no * items_per_page

                try:
                    logging.info(
                        "Fetching MOF category_id=%s offset=%s limit=%s",
                        category_id,
                        offset,
                        items_per_page,
                    )
                    payload = fetch_listing_page(
                        session=session,
                        category_id=category_id,
                        offset=offset,
                        limit=items_per_page,
                    )
                    listing_articles = extract_listing_articles(payload, category_id=category_id)

                    if not listing_articles:
                        logging.info("No articles found for category_id=%s offset=%s", category_id, offset)
                        break

                    should_stop = False

                    for article in listing_articles:
                        if len(results) >= max_articles:
                            break

                        if is_older_than_window(article.published_at, days, now=now):
                            logging.info("Stop at old article date: %s", article.title)
                            should_stop = True
                            break

                        if article.url in seen_links:
                            continue
                        seen_links.add(article.url)

                        if not article.title:
                            logging.info("Skip article without title: %s", article.url)
                            continue

                        if not is_within_days(article.published_at, days, now=now):
                            logging.info("Skip old article: %s", article.title)
                            continue

                        if filter_relevant and not is_relevant_article(
                            article,
                            require_legal_keyword=require_legal_keyword,
                            require_topic_keyword=require_topic_keyword,
                        ):
                            logging.info("Skip irrelevant article: %s", article.title)
                            continue

                        results.append(article_to_json_dict(article))

                    if should_stop or len(listing_articles) < items_per_page:
                        break

                    time.sleep(POLITE_DELAY_SECONDS)

                except Exception as exc:
                    logging.warning(
                        "Failed category_id=%s offset=%s: %s",
                        category_id,
                        offset,
                        exc,
                    )
                    break

            if len(results) >= max_articles:
                break
    finally:
        if own_session:
            session.close()

    logging.info("Finished. Parsed %d relevant articles.", len(results))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crawl MOF and export legal/IP-tech updates as JSON."
    )
    parser.add_argument(
        "--category-ids",
        type=str,
        default=",".join(DEFAULT_CATEGORY_IDS),
        help="Danh sách categoryId, ngăn cách bằng dấu phẩy. Mặc định: 3 chuyên mục MOF.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=1,
        help="Chỉ lấy bài trong N ngày theo lịch gần nhất. Mặc định: 1 là hôm nay. Dùng --days 0 để bỏ lọc ngày.",
    )
    parser.add_argument(
        "--max-articles",
        type=int,
        default=50,
        help="Số bài tối đa trả về. Mặc định: 50.",
    )
    parser.add_argument(
        "--items-per-page",
        type=int,
        default=DEFAULT_ITEMS_PER_PAGE,
        help="Số bài mỗi page API. Mặc định: 10.",
    )
    parser.add_argument(
        "--max-pages-per-category",
        type=int,
        default=5,
        help="Số page tối đa cho mỗi category. Mặc định: 5.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="mof_articles.json",
        help="File JSON output.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="In JSON đẹp ra màn hình.",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    articles = crawl_mof(
        category_ids=parse_category_ids(args.category_ids),
        days=None if args.days == 0 else args.days,
        max_articles=args.max_articles,
        items_per_page=args.items_per_page,
        max_pages_per_category=args.max_pages_per_category,
        filter_relevant=True,
        require_legal_keyword=True,
        require_topic_keyword=True,
    )

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)

    if args.pretty:
        print(json.dumps(articles, ensure_ascii=False, indent=2))

    print(f"Saved {len(articles)} articles to {args.output}")


if __name__ == "__main__":
    main()
