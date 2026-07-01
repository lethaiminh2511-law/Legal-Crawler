from __future__ import annotations

import argparse
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from crawlers.common.keywords import LEGAL_KEYWORDS, TOPIC_KEYWORDS

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

SOURCE_NAME = "Cục Bản quyền tác giả"
DEFAULT_CATEGORY_URL = "https://cov.gov.vn/tin-tuc/"

ARTICLE_URL_PATTERN = re.compile(r"/.+-\d+\.html$", re.IGNORECASE)
DATE_PATTERNS = [
    re.compile(r"\b(\d{1,2}:\d{2}),\s*(\d{1,2}/\d{1,2}/\d{4})\b"),
    re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}:\d{2})\b"),
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; LegalTrackBot/1.0; "
        "+https://example.com/bot-info)"
    )
}

REQUEST_TIMEOUT = 20
POLITE_DELAY_SECONDS = 0.8


@dataclass
class ParsedArticle:
    title: str
    url: str
    source: str
    published_at: Optional[str]
    summary_raw: str


def clean_text(text: Optional[str]) -> str:
    if not text:
        return ""
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_for_search(text: str) -> str:
    return clean_text(text).lower()


def fetch_html(session: requests.Session, url: str) -> str:
    response = session.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)

    # COV currently returns HTTP 404 for /tin-tuc/?page=N while serving valid HTML.
    if response.status_code != 404:
        response.raise_for_status()
    elif "<html" not in response.text.lower():
        response.raise_for_status()

    if not response.encoding or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding

    return response.text


def build_page_url(category_url: str, page: int) -> str:
    if "?" in category_url:
        separator = "&" if not category_url.endswith(("?", "&")) else ""
        return f"{category_url}{separator}page={page}"
    return f"{category_url.rstrip('/')}/?page={page}"


def is_cov_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.netloc.endswith("cov.gov.vn")


def is_article_url(url: str) -> bool:
    parsed = urlparse(url)
    if not is_cov_url(url):
        return False
    if parsed.path.startswith("/van-ban-phap-luat.html"):
        return False
    return bool(ARTICLE_URL_PATTERN.search(parsed.path))


def extract_meta_content(soup: BeautifulSoup, *selectors: tuple[str, str]) -> str:
    for attr_name, attr_value in selectors:
        tag = soup.find("meta", attrs={attr_name: attr_value})
        if tag and tag.get("content"):
            return clean_text(tag.get("content"))
    return ""


def try_parse_datetime(raw: str) -> Optional[datetime]:
    raw = clean_text(raw)
    if not raw:
        return None

    if raw.endswith("Z"):
        raw = raw[:-1] + "+0000"

    for pattern in DATE_PATTERNS:
        match = pattern.search(raw)
        if match:
            if ":" in match.group(1):
                raw = f"{match.group(2)} {match.group(1)}"
            else:
                raw = f"{match.group(1)} {match.group(2)}"
            break
    else:
        weekday_match = re.search(
            r"(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}:\d{2})",
            raw,
        )
        if weekday_match:
            raw = f"{weekday_match.group(1)} {weekday_match.group(2)}"

    candidates = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
        "%Y-%m-%d",
    ]

    for fmt in candidates:
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=VN_TZ)
            return dt.astimezone(VN_TZ)
        except ValueError:
            continue

    return None


def format_datetime(raw: str) -> Optional[str]:
    parsed = try_parse_datetime(raw)
    if not parsed:
        return None
    return parsed.strftime("%Y-%m-%d %H:%M")


def extract_listing_article(article_tag: BeautifulSoup, page_url: str) -> Optional[ParsedArticle]:
    title_link = article_tag.select_one(".story__title a[href]")
    if not title_link:
        title_link = article_tag.find("a", href=True)
    if not title_link:
        return None

    url = urljoin(page_url, clean_text(title_link.get("href"))).split("#")[0].strip()
    if not is_article_url(url):
        return None

    title = clean_text(title_link.get("title") or title_link.get_text(" "))
    summary_tag = article_tag.select_one(".story__summary")
    time_tag = article_tag.find("time")
    published_at = None

    if time_tag:
        published_at = format_datetime(
            clean_text(time_tag.get("datetime") or time_tag.get_text(" "))
        )

    return ParsedArticle(
        title=title,
        url=url,
        source=SOURCE_NAME,
        published_at=published_at,
        summary_raw=clean_text(summary_tag.get_text(" ")) if summary_tag else "",
    )


def extract_listing_articles(html: str, page_url: str) -> list[ParsedArticle]:
    soup = BeautifulSoup(html, "html.parser")
    articles: list[ParsedArticle] = []

    for selector in [
        "section.zone--highlight article.story",
        "section.zone--timeline article.story",
    ]:
        for article_tag in soup.select(selector):
            article = extract_listing_article(article_tag, page_url)
            if article:
                articles.append(article)

    seen = set()
    unique_articles = []
    for article in articles:
        if article.url not in seen:
            seen.add(article.url)
            unique_articles.append(article)

    return unique_articles


def extract_title(soup: BeautifulSoup) -> str:
    detail_title = soup.select_one(".detail__title")
    if detail_title:
        title = clean_text(detail_title.get_text(" "))
        if title:
            return title

    h1 = soup.find("h1")
    if h1:
        title = clean_text(h1.get_text(" "))
        if title:
            return title

    og_title = extract_meta_content(soup, ("property", "og:title"))
    if og_title:
        return og_title.replace(" | Cục Bản quyền tác giả", "").strip()

    if soup.title:
        return clean_text(soup.title.get_text(" ")).replace(
            " | Cục Bản quyền tác giả", ""
        ).strip()

    return ""


def extract_published_at(soup: BeautifulSoup) -> Optional[str]:
    meta_date = extract_meta_content(
        soup,
        ("property", "article:published_time"),
        ("name", "pubdate"),
        ("name", "publishdate"),
        ("name", "date"),
    )
    if meta_date:
        published_at = format_datetime(meta_date)
        if published_at:
            return published_at

    detail_time = soup.select_one(".detail__time time")
    if detail_time:
        published_at = format_datetime(detail_time.get("datetime") or detail_time.get_text(" "))
        if published_at:
            return published_at

    page_text = clean_text(soup.get_text(" "))
    for pattern in DATE_PATTERNS:
        match = pattern.search(page_text)
        if match:
            published_at = format_datetime(match.group(0))
            if published_at:
                return published_at

    return None


def remove_noise(soup: BeautifulSoup) -> None:
    for tag in soup(["script", "style", "noscript", "iframe", "svg"]):
        tag.decompose()

    for selector in [
        ".detail__credit",
        ".detail__footer",
        ".detail__social",
        ".detail__tag",
        ".zone",
        ".qc",
    ]:
        for tag in soup.select(selector):
            tag.decompose()


def extract_summary(soup: BeautifulSoup) -> str:
    detail_summary = soup.select_one(".detail__summary")
    if detail_summary:
        summary = clean_text(detail_summary.get_text(" "))
        if summary:
            return summary

    meta_description = extract_meta_content(
        soup,
        ("name", "description"),
        ("property", "og:description"),
    )
    if meta_description:
        return meta_description

    content = soup.select_one("#abody, .detail__content, article")
    if not content:
        return ""

    content = BeautifulSoup(str(content), "html.parser")
    remove_noise(content)

    for tag in content.find_all(["p", "div"], recursive=True):
        text = clean_text(tag.get_text(" "))
        if len(text) >= 30:
            return text

    return ""


def parse_article(html: str, url: str, fallback: Optional[ParsedArticle] = None) -> ParsedArticle:
    soup = BeautifulSoup(html, "html.parser")

    title = extract_title(soup)
    published_at = extract_published_at(soup)
    summary_raw = extract_summary(soup)

    return ParsedArticle(
        title=title or (fallback.title if fallback else ""),
        url=url,
        source=SOURCE_NAME,
        published_at=published_at or (fallback.published_at if fallback else None),
        summary_raw=summary_raw or (fallback.summary_raw if fallback else ""),
    )


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


def is_within_days(published_at: Optional[str], days: Optional[int]) -> bool:
    if days is None:
        return True

    if not published_at:
        return True

    parsed = try_parse_datetime(published_at)
    if not parsed:
        return True

    cutoff = datetime.now(VN_TZ) - timedelta(days=days)
    return parsed >= cutoff


def is_before_days(published_at: Optional[str], days: Optional[int]) -> bool:
    if days is None or not published_at:
        return False

    parsed = try_parse_datetime(published_at)
    if not parsed:
        return False

    cutoff = datetime.now(VN_TZ) - timedelta(days=days)
    return parsed < cutoff


def article_to_json_dict(article: ParsedArticle) -> dict:
    return {
        "title": article.title,
        "url": article.url,
        "source": article.source,
        "published_at": article.published_at,
        "summary_raw": article.summary_raw,
    }


def crawl_cov(
    category_url: str = DEFAULT_CATEGORY_URL,
    start_page: int = 1,
    max_pages: int = 5,
    days: Optional[int] = 7,
    max_articles: int = 50,
    filter_relevant: bool = True,
    require_legal_keyword: bool = True,
    require_topic_keyword: bool = True,
) -> list[dict]:
    """
    Main function để đưa vào hệ thống.

    Returns:
        list[dict] theo format:
        {
          "title": "...",
          "url": "...",
          "source": "Cục Bản quyền tác giả",
          "published_at": "2026-06-08 18:41",
          "summary_raw": "..."
        }
    """
    logging.info("Start crawling COV")

    session = requests.Session()
    seen_links: set[str] = set()
    results: list[dict] = []
    stop_crawling = False

    for page in range(start_page, start_page + max_pages):
        if stop_crawling or len(results) >= max_articles:
            break

        try:
            page_url = build_page_url(category_url, page)
            logging.info("Fetching category page: %s", page_url)
            html = fetch_html(session, page_url)
            listing_articles = extract_listing_articles(html, page_url)
            logging.info("Found %d article links from %s", len(listing_articles), page_url)

            if not listing_articles:
                break

            time.sleep(POLITE_DELAY_SECONDS)
        except Exception as exc:
            logging.warning("Failed to fetch category page %s: %s", page, exc)
            break

        for fallback_article in listing_articles:
            if len(results) >= max_articles:
                break
            if fallback_article.url in seen_links:
                continue
            seen_links.add(fallback_article.url)

            try:
                logging.info("Fetching article: %s", fallback_article.url)
                html = fetch_html(session, fallback_article.url)
                article = parse_article(html, fallback_article.url, fallback=fallback_article)

                if not article.title:
                    logging.info("Skip article without title: %s", fallback_article.url)
                    continue

                if is_before_days(article.published_at, days):
                    logging.info(
                        "Stop crawling because article is older than range: %s (%s)",
                        fallback_article.url,
                        article.published_at,
                    )
                    stop_crawling = True
                    break

                if filter_relevant and not is_relevant_article(
                    article,
                    require_legal_keyword=require_legal_keyword,
                    require_topic_keyword=require_topic_keyword,
                ):
                    logging.info("Skip irrelevant article: %s", fallback_article.url)
                    continue

                results.append(article_to_json_dict(article))
                time.sleep(POLITE_DELAY_SECONDS)
            except Exception as exc:
                logging.warning("Failed to parse article %s: %s", fallback_article.url, exc)

    logging.info("Finished. Parsed %d relevant articles.", len(results))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crawl COV and export legal/copyright updates as JSON."
    )
    parser.add_argument(
        "--category-url",
        type=str,
        default=DEFAULT_CATEGORY_URL,
        help="URL chuyên mục. Mặc định: https://cov.gov.vn/tin-tuc/.",
    )
    parser.add_argument(
        "--start-page",
        type=int,
        default=1,
        help="Page bắt đầu crawl. Mặc định: 1.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=5,
        help="Số page tối đa cần crawl. Mặc định: 5.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=1,
        help="Chỉ lấy bài trong N ngày gần nhất. Mặc định: 1. Dùng --days 0 để bỏ lọc ngày.",
    )
    parser.add_argument(
        "--max-articles",
        type=int,
        default=50,
        help="Số bài tối đa trả về. Mặc định: 50.",
    )
    parser.add_argument(
        "--no-filter",
        action="store_true",
        help="Không lọc keyword; lấy tất cả bài tìm được từ category pages.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="cov_articles.json",
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

    articles = crawl_cov(
        category_url=args.category_url,
        start_page=args.start_page,
        max_pages=args.max_pages,
        days=None if args.days == 0 else args.days,
        max_articles=args.max_articles,
        filter_relevant=not args.no_filter,
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
