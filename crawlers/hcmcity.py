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
from typing import Optional
from urllib.parse import urljoin, urlparse, urlunparse
from zoneinfo import ZoneInfo

import requests
import urllib3
from bs4 import BeautifulSoup

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crawlers.common.keywords import LEGAL_KEYWORDS, TOPIC_KEYWORDS, keyword_hits
from crawlers.common.text import normalize_for_search

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

SOURCE_NAME = "Cổng thông tin điện tử Thành phố Hồ Chí Minh"
BASE_SITE_URL = "https://hochiminhcity.gov.vn/"
ASSET_PUBLISHER_INSTANCE_ID = "iwwYBC4Hj8wV"
ASSET_PUBLISHER_PARAM = (
    "_com_liferay_asset_publisher_web_portlet_AssetPublisherPortlet_INSTANCE_"
    f"{ASSET_PUBLISHER_INSTANCE_ID}_cur"
)

DEFAULT_PREFIXES = [
    "https://hochiminhcity.gov.vn/tin-t%E1%BB%A9c-s%E1%BB%B1-ki%E1%BB%87n-all-",
]
DEFAULT_ITEMS_PER_PAGE = 10

DATE_PATTERNS = [
    re.compile(r"\b(\d{1,2}:\d{2})\s*\|\s*(\d{2}/\d{2}/\d{4})\b"),
    re.compile(r"\b(\d{2}/\d{2}/\d{4})(?:\s*(?:\||-|,)?\s*(\d{1,2}:\d{2}))?\b"),
]

HEADERS = {
    "accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "accept-language": "en,vi;q=0.9,en-US;q=0.8",
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


def clean_text(text: Optional[str]) -> str:
    if not text:
        return ""
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(query="", fragment=""))


def fetch_html(session: requests.Session, url: str, verify_ssl: bool) -> str:
    response = session.get(url=url, timeout=REQUEST_TIMEOUT, verify=verify_ssl)
    response.raise_for_status()

    if not response.encoding or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding

    return response.text


def build_listing_url(
    prefix: str,
    page_no: int,
    items_per_page: int = DEFAULT_ITEMS_PER_PAGE,
) -> str:
    del items_per_page
    separator = "&" if "?" in prefix else "?"
    base = re.sub(rf"([?&]){re.escape(ASSET_PUBLISHER_PARAM)}=\d+", r"\1", prefix)
    base = base.rstrip("?&")
    return f"{base}{separator}{ASSET_PUBLISHER_PARAM}={page_no}"


def try_parse_datetime(raw: Optional[str]) -> Optional[datetime]:
    raw_text = clean_text(raw)
    if not raw_text:
        return None

    candidates: list[str] = []
    time_first = DATE_PATTERNS[0].search(raw_text)
    if time_first:
        candidates.append(f"{time_first.group(2)} {time_first.group(1)}")

    date_first = DATE_PATTERNS[1].search(raw_text)
    if date_first:
        date_value = date_first.group(1)
        if date_first.group(2):
            candidates.append(f"{date_value} {date_first.group(2)}")
        candidates.append(date_value)

    candidates.extend(
        [
            raw_text,
            raw_text.replace(" CH", "").replace(" SA", ""),
        ]
    )

    for candidate in candidates:
        candidate = clean_text(candidate)
        for fmt in [
            "%d/%m/%Y %H:%M",
            "%d/%m/%Y",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
        ]:
            try:
                dt = datetime.strptime(candidate, fmt)
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


def extract_listing_date(node: BeautifulSoup) -> Optional[str]:
    date_node = node.select_one(".text-date-sklh")
    raw_text = date_node.get_text(" ") if date_node else node.get_text(" ")
    return format_datetime(raw_text)


def normalize_title(title: str) -> str:
    title = clean_text(title)
    suffixes = [
        " - Cổng thông tin Thành Phố Hồ Chí Minh",
        " - Cổng thông tin Thành Phố Hồ Chí Minh - Liferay",
    ]
    for suffix in suffixes:
        if title.endswith(suffix):
            return title[: -len(suffix)].strip()
    return title


def build_listing_article(node: BeautifulSoup, category_url: str) -> Optional[ParsedArticle]:
    title_node = node.select_one(".d-md-block .asset-publisher-title") or node.select_one(
        ".asset-publisher-title"
    )
    link_node = title_node.find_parent("a", href=True) if title_node else node.select_one("a[href]")
    if not title_node or not link_node:
        return None

    title = clean_text(title_node.get("title") or title_node.get_text(" "))
    href = clean_text(link_node.get("href"))
    if not title or not href or "/web/hcm/-/" not in href:
        return None

    summary_node = node.select_one(".d-md-block .limit-tin-descc-news") or node.select_one(
        ".limit-tin-descc-news"
    )
    summary = clean_text(summary_node.get_text(" ") if summary_node else "")

    return ParsedArticle(
        title=title,
        url=canonicalize_url(urljoin(BASE_SITE_URL, href)),
        source=SOURCE_NAME,
        published_at=extract_listing_date(node),
        summary_raw=summary,
        category_url=category_url,
    )


def extract_listing_articles(html: str, category_url: str) -> list[ParsedArticle]:
    soup = BeautifulSoup(html, "html.parser")
    articles: list[ParsedArticle] = []
    seen_links: set[str] = set()

    for node in soup.select(".news-items .news-item"):
        article = build_listing_article(node, category_url=category_url)
        if not article or article.url in seen_links:
            continue

        seen_links.add(article.url)
        articles.append(article)

    return articles


def extract_title(soup: BeautifulSoup) -> str:
    for selector in [".title-divvv", "h1", "h2", "h3"]:
        node = soup.select_one(selector)
        if node:
            title = normalize_title(node.get_text(" "))
            if title:
                return title

    og_title = extract_meta_content(soup, ("property", "og:title"), ("name", "DC.Title"))
    if og_title:
        return normalize_title(og_title)

    if soup.title:
        return normalize_title(soup.title.get_text(" "))

    return ""


def extract_published_at(soup: BeautifulSoup) -> Optional[str]:
    for selector in [".sp-dislaydate", "time"]:
        node = soup.select_one(selector)
        if not node:
            continue
        parsed = format_datetime(node.get("datetime") if node.name == "time" else node.get_text(" "))
        if parsed:
            return parsed

    page_text = clean_text(soup.get_text(" "))
    return format_datetime(page_text)


def extract_summary(soup: BeautifulSoup) -> str:
    summary_node = soup.select_one(".text-summary")
    if summary_node:
        summary = clean_text(summary_node.get_text(" "))
        if summary:
            return summary

    return extract_meta_content(
        soup,
        ("name", "description"),
        ("property", "og:description"),
        ("name", "DC.Description"),
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
    searchable_text = normalize_for_search(" ".join([article.title, article.summary_raw]))

    legal_hits = keyword_hits(searchable_text, LEGAL_KEYWORDS)
    topic_hits = keyword_hits(searchable_text, TOPIC_KEYWORDS)

    if require_legal_keyword and not legal_hits:
        return False

    if require_topic_keyword and not topic_hits:
        return False

    return True


def get_start_date(days: Optional[int]) -> Optional[datetime.date]:
    if days is None:
        return None

    day_count = max(days, 1)
    return (datetime.now(VN_TZ) - timedelta(days=day_count - 1)).date()


def is_within_days(published_at: Optional[str], days: Optional[int]) -> bool:
    start_date = get_start_date(days)
    if start_date is None:
        return True

    if not published_at:
        return True

    parsed = try_parse_datetime(published_at)
    if not parsed:
        return True

    return parsed.date() >= start_date


def is_older_than_window(published_at: Optional[str], days: Optional[int]) -> bool:
    start_date = get_start_date(days)
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

    if not parsed_dates:
        return None

    return min(parsed_dates)


def should_stop_after_page(articles: list[ParsedArticle], days: Optional[int]) -> bool:
    oldest_date = get_oldest_article_date(articles)
    if not oldest_date:
        return False

    return is_older_than_window(oldest_date.strftime("%Y-%m-%d %H:%M"), days)


def article_to_json_dict(article: ParsedArticle) -> dict:
    return {
        "title": article.title,
        "url": article.url,
        "source": article.source,
        "published_at": article.published_at,
        "summary_raw": article.summary_raw,
        "category_url": article.category_url,
    }


def crawl_hcmcity(
    prefixes: Optional[list[str]] = None,
    days: Optional[int] = 1,
    max_articles: int = 50,
    items_per_page: int = DEFAULT_ITEMS_PER_PAGE,
    max_pages_per_prefix: int = 5,
    filter_relevant: bool = True,
    require_legal_keyword: bool = True,
    require_topic_keyword: bool = True,
    fetch_details: bool = True,
    verify_ssl: bool = False,
    session: Optional[requests.Session] = None,
) -> list[dict]:
    """
    Main function để đưa vào hệ thống.

    Returns:
        list[dict] theo format:
        {
          "title": "...",
          "url": "...",
          "source": "Cổng thông tin điện tử Thành phố Hồ Chí Minh",
          "published_at": "2026-07-10 16:43",
          "summary_raw": "...",
          "category_url": "https://hochiminhcity.gov.vn/..."
        }
    """
    logging.info("Start crawling HCMC news listings")

    if not verify_ssl:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    session = session or requests.Session()
    session.headers.update(HEADERS)

    results: list[dict] = []
    seen_links: set[str] = set()

    for prefix in prefixes or DEFAULT_PREFIXES:
        logging.info("Start prefix=%s", prefix)

        for page_no in range(1, max_pages_per_prefix + 1):
            if len(results) >= max_articles:
                break

            listing_url = build_listing_url(
                prefix=prefix,
                page_no=page_no,
                items_per_page=items_per_page,
            )

            try:
                logging.info("Fetching HCMC prefix=%s page_no=%s", prefix, page_no)
                html = fetch_html(session, listing_url, verify_ssl=verify_ssl)
                listing_articles = extract_listing_articles(html, category_url=prefix)

                if not listing_articles:
                    logging.info("No articles found for prefix=%s page_no=%s", prefix, page_no)
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
                            detail_html = fetch_html(session, listing_article.url, verify_ssl=verify_ssl)
                            article = parse_article_detail(detail_html, fallback=listing_article)
                            time.sleep(POLITE_DELAY_SECONDS)
                        except Exception as exc:
                            logging.warning("Failed to fetch detail %s: %s", listing_article.url, exc)

                    page_articles.append(article)

                    if not article.title:
                        logging.info("Skip article without title: %s", listing_article.url)
                        continue

                    if not is_within_days(article.published_at, days):
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

                if should_stop_after_page(page_articles, days):
                    oldest_date = get_oldest_article_date(page_articles)
                    logging.info(
                        "Skip next page because page_no=%s oldest date is %s",
                        page_no,
                        oldest_date.strftime("%Y-%m-%d %H:%M") if oldest_date else None,
                    )
                    break

                time.sleep(POLITE_DELAY_SECONDS)

                if len(listing_articles) < items_per_page:
                    break

            except Exception as exc:
                logging.warning("Failed prefix=%s page_no=%s: %s", prefix, page_no, exc)
                break

    logging.info("Finished. Parsed %d relevant articles.", len(results))
    return results


def parse_prefixes(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crawl HCMC city news and export legal/IP-tech updates as JSON."
    )
    parser.add_argument(
        "--prefixes",
        type=str,
        default=",".join(DEFAULT_PREFIXES),
        help="Danh sách prefix URL, ngăn cách bằng dấu phẩy. Mặc định: tất cả tin HCMC.",
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
        help="Số bài mỗi page. Mặc định: 10.",
    )
    parser.add_argument(
        "--max-pages-per-prefix",
        type=int,
        default=5,
        help="Số page tối đa cho mỗi prefix. Mặc định: 5.",
    )
    parser.add_argument(
        "--no-detail",
        action="store_true",
        help="Không fetch từng trang chi tiết; chỉ dùng dữ liệu listing.",
    )
    parser.add_argument(
        "--verify-ssl",
        action="store_true",
        help="Bật xác thực SSL. Mặc định tắt để phù hợp các môi trường crawl thiếu CA chain.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="hcmcity_articles.json",
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

    articles = crawl_hcmcity(
        prefixes=parse_prefixes(args.prefixes),
        days=None if args.days == 0 else args.days,
        max_articles=args.max_articles,
        items_per_page=args.items_per_page,
        max_pages_per_prefix=args.max_pages_per_prefix,
        filter_relevant=True,
        require_legal_keyword=True,
        require_topic_keyword=True,
        fetch_details=not args.no_detail,
        verify_ssl=args.verify_ssl,
    )

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)

    if args.pretty:
        print(json.dumps(articles, ensure_ascii=False, indent=2))

    print(f"Saved {len(articles)} articles to {args.output}")


if __name__ == "__main__":
    main()
