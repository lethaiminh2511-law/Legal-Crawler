from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin, urlparse, urlunparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crawlers.common.keywords import LEGAL_KEYWORDS, TOPIC_KEYWORDS, keyword_hits

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

SOURCE_NAME = "Cổng thông tin điện tử Thành phố Hà Nội"
BASE_SITE_URL = "https://hanoi.gov.vn/"
API_URL = "https://hanoi.gov.vn/api/NewsZone/NewsZone"
DEFAULT_CATEGORY_URL = "https://hanoi.gov.vn/chi-dao-cua-ubnd-thanh-pho-ha-noi"

DEFAULT_PAGE_SIZE = "DxZD1w2i+8E="
DEFAULT_CATNAME = "fFeUG2QagshQSId/gnsY7cA7vzDD4bMURXrY7ae9cm68FyOjl3l+4A=="
DEFAULT_LANGUAGE_ID = "jM2HDDVEz40="
DEFAULT_SITE = "/CP0MQRJUt0="
DEFAULT_DATA_IDS = [
    "4260710170406828",
    "4260710162005529",
    "4260710162347732",
    "4260710095537598",
]

DATE_PATTERN = re.compile(
    r"\b(?:(\d{1,2}:\d{2})\s*,\s*)?(\d{1,2}/\d{1,2}/\d{4})\b",
    re.IGNORECASE,
)

HEADERS = {
    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    "user-agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/149.0.0.0 Safari/537.36"
    ),
    "sec-ch-ua": '"Google Chrome";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
    "sec-ch-ua-platform": '"Linux"',
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


def clean_text(text: Any) -> str:
    if text is None:
        return ""
    normalized = str(text).replace("\xa0", " ")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(query="", fragment=""))


def build_form_data(page_index: int) -> dict[str, Any]:
    return {
        "PageIndex": str(max(page_index, 0)),
        "PageSize": DEFAULT_PAGE_SIZE,
        "Catname": DEFAULT_CATNAME,
        "LanguageId": DEFAULT_LANGUAGE_ID,
        "Site": DEFAULT_SITE,
        "DataIds[]": DEFAULT_DATA_IDS,
    }


def fetch_listing_html(session: requests.Session, page_index: int) -> str:
    response = session.post(
        API_URL,
        data=build_form_data(page_index),
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    if not response.encoding or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding

    return response.text


def fetch_html(session: requests.Session, url: str) -> str:
    response = session.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    if not response.encoding or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding

    return response.text


def try_parse_datetime(raw: Optional[str]) -> Optional[datetime]:
    raw_text = clean_text(raw)
    if not raw_text:
        return None

    match = DATE_PATTERN.search(raw_text)
    if match:
        raw_text = match.group(2)
        if match.group(1):
            raw_text = f"{match.group(2)} {match.group(1)}"

    candidates = [
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ]

    if raw_text.endswith("Z"):
        raw_text = raw_text[:-1] + "+0000"

    for fmt in candidates:
        try:
            dt = datetime.strptime(raw_text, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=VN_TZ)
            return dt.astimezone(VN_TZ)
        except ValueError:
            continue

    return None


def format_datetime(raw: Optional[str]) -> Optional[str]:
    parsed = try_parse_datetime(raw)
    if not parsed:
        return None
    return parsed.strftime("%Y-%m-%d %H:%M")


def extract_meta_content(soup: BeautifulSoup, *selectors: tuple[str, str]) -> str:
    for attr_name, attr_value in selectors:
        tag = soup.find("meta", attrs={attr_name: attr_value})
        if tag and tag.get("content"):
            return clean_text(tag.get("content"))
    return ""


def extract_json_ld_values(soup: BeautifulSoup) -> dict[str, str]:
    values: dict[str, str] = {}

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text()
        if not raw:
            continue

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue

        candidates = payload if isinstance(payload, list) else [payload]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            for key in ["headline", "name", "description", "datePublished"]:
                value = candidate.get(key)
                if isinstance(value, str) and value.strip():
                    values.setdefault(key, value)

    return values


def extract_listing_date(node: BeautifulSoup) -> Optional[str]:
    time_node = node.select_one(".news-time")
    raw = ""
    if time_node:
        raw = clean_text(time_node.get("title")) or clean_text(time_node.get_text(" "))
    return format_datetime(raw)


def extract_listing_articles(
    html: str,
    category_url: str = DEFAULT_CATEGORY_URL,
) -> list[ParsedArticle]:
    soup = BeautifulSoup(html, "html.parser")
    articles: list[ParsedArticle] = []
    seen_links: set[str] = set()

    for node in soup.select(".news-item"):
        title_tag = node.select_one(".news-title")
        link_tag = node.select_one("a[href]")
        if not title_tag or not link_tag:
            continue

        title = clean_text(title_tag.get_text(" ")) or clean_text(link_tag.get("title"))
        href = clean_text(link_tag.get("href"))
        if not title or not href:
            continue

        url = canonicalize_url(urljoin(BASE_SITE_URL, href))
        if url in seen_links:
            continue
        seen_links.add(url)

        summary_node = node.select_one(".news-sapo")
        articles.append(
            ParsedArticle(
                title=title,
                url=url,
                source=SOURCE_NAME,
                published_at=extract_listing_date(node),
                summary_raw=clean_text(summary_node.get_text(" ") if summary_node else ""),
                category_url=category_url,
            )
        )

    return articles


def extract_title(soup: BeautifulSoup) -> str:
    for selector in ["h1", ".title-detail", ".news-title"]:
        node = soup.select_one(selector)
        if node:
            title = clean_text(node.get_text(" "))
            if title:
                return title

    json_ld = extract_json_ld_values(soup)
    if json_ld.get("headline"):
        return clean_text(json_ld["headline"])
    if json_ld.get("name"):
        return clean_text(json_ld["name"])

    return extract_meta_content(soup, ("property", "og:title"), ("name", "DC.Title"))


def extract_published_at(soup: BeautifulSoup) -> Optional[str]:
    json_ld = extract_json_ld_values(soup)
    if json_ld.get("datePublished"):
        parsed = format_datetime(json_ld["datePublished"])
        if parsed:
            return parsed

    for selector in [".date", ".news-date", ".time", ".news-time"]:
        node = soup.select_one(selector)
        if not node:
            continue
        parsed = format_datetime(node.get("title") or node.get_text(" "))
        if parsed:
            return parsed

    return format_datetime(extract_meta_content(soup, ("property", "article:published_time")))


def extract_summary(soup: BeautifulSoup) -> str:
    json_ld = extract_json_ld_values(soup)
    return (
        extract_meta_content(
            soup,
            ("name", "description"),
            ("property", "og:description"),
            ("name", "DC.Description"),
        )
        or clean_text(json_ld.get("description"))
    )


def parse_article_detail(html: str, fallback: ParsedArticle) -> ParsedArticle:
    soup = BeautifulSoup(html, "html.parser")

    return ParsedArticle(
        title=extract_title(soup) or fallback.title,
        url=fallback.url,
        source=SOURCE_NAME,
        published_at=extract_published_at(soup) or fallback.published_at,
        summary_raw=extract_summary(soup) or fallback.summary_raw,
        category_url=fallback.category_url,
    )


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
    if start_date is None or not published_at:
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


def get_oldest_article_date(articles: list[ParsedArticle]) -> Optional[datetime]:
    parsed_dates = [
        parsed
        for parsed in (try_parse_datetime(article.published_at) for article in articles)
        if parsed is not None
    ]
    return min(parsed_dates) if parsed_dates else None


def should_stop_after_page(
    articles: list[ParsedArticle],
    days: Optional[int],
    now: Optional[datetime] = None,
) -> bool:
    oldest_date = get_oldest_article_date(articles)
    if not oldest_date:
        return False
    return is_older_than_window(oldest_date.strftime("%Y-%m-%d %H:%M"), days, now=now)


def article_to_json_dict(article: ParsedArticle) -> dict[str, Optional[str]]:
    return {
        "title": article.title,
        "url": article.url,
        "source": article.source,
        "published_at": article.published_at,
        "summary_raw": article.summary_raw,
        "category_url": article.category_url,
    }


def crawl_ubndhn(
    days: Optional[int] = 1,
    max_articles: int = 50,
    max_pages: int = 5,
    filter_relevant: bool = True,
    require_legal_keyword: bool = True,
    require_topic_keyword: bool = True,
    fetch_details: bool = True,
    session: Optional[requests.Session] = None,
    now: Optional[datetime] = None,
) -> list[dict]:
    """
    Main function để đưa vào hệ thống.

    Returns:
        list[dict] theo format tương tự các crawler khác trong repo.
    """
    logging.info("Start crawling Hanoi UBND NewsZone API")

    active_session = session or requests.Session()
    active_session.headers.update(HEADERS)

    results: list[dict] = []
    seen_links: set[str] = set()

    for page_index in range(max_pages):
        if len(results) >= max_articles:
            break

        try:
            logging.info("Fetching Hanoi UBND page_index=%s", page_index)
            html = fetch_listing_html(active_session, page_index)
            listing_articles = extract_listing_articles(html)

            if not listing_articles:
                logging.info("No articles found for page_index=%s", page_index)
                break

            page_articles: list[ParsedArticle] = []

            for listing_article in listing_articles:
                if len(results) >= max_articles:
                    break
                if listing_article.url in seen_links:
                    continue
                seen_links.add(listing_article.url)

                article = listing_article
                if fetch_details:
                    try:
                        detail_html = fetch_html(active_session, listing_article.url)
                        article = parse_article_detail(detail_html, fallback=listing_article)
                        time.sleep(POLITE_DELAY_SECONDS)
                    except Exception as exc:
                        logging.warning("Failed to fetch detail %s: %s", listing_article.url, exc)

                page_articles.append(article)

                if not article.title:
                    logging.info("Skip article without title: %s", listing_article.url)
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

            if should_stop_after_page(page_articles, days, now=now):
                oldest_date = get_oldest_article_date(page_articles)
                logging.info(
                    "Skip next page because page_index=%s oldest date is %s",
                    page_index,
                    oldest_date.strftime("%Y-%m-%d %H:%M") if oldest_date else None,
                )
                break

            time.sleep(POLITE_DELAY_SECONDS)

        except Exception as exc:
            logging.warning("Failed page_index=%s: %s", page_index, exc)
            break

    logging.info("Finished. Parsed %d relevant articles.", len(results))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crawl Hanoi UBND NewsZone API and export legal/tech updates as JSON."
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
        "--max-pages",
        type=int,
        default=5,
        help="Số page API tối đa. PageIndex bắt đầu từ 0. Mặc định: 5.",
    )
    parser.add_argument(
        "--no-filter",
        action="store_true",
        help="Không lọc keyword; lấy tất cả bài tìm được.",
    )
    parser.add_argument(
        "--no-detail",
        action="store_true",
        help="Không fetch từng trang chi tiết; chỉ dùng dữ liệu listing.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="ubndhn_articles.json",
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

    articles = crawl_ubndhn(
        days=None if args.days == 0 else args.days,
        max_articles=args.max_articles,
        max_pages=args.max_pages,
        filter_relevant=not args.no_filter,
        require_legal_keyword=True,
        require_topic_keyword=True,
        fetch_details=not args.no_detail,
    )

    with open(args.output, "w", encoding="utf-8") as file:
        json.dump(articles, file, ensure_ascii=False, indent=2)

    if args.pretty:
        print(json.dumps(articles, ensure_ascii=False, indent=2))

    print(f"Saved {len(articles)} articles to {args.output}")


if __name__ == "__main__":
    main()
