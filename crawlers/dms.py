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
from urllib.parse import unquote, urlencode, urljoin, urlparse, urlunparse
from zoneinfo import ZoneInfo

import requests
import urllib3
from bs4 import BeautifulSoup

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crawlers.common.keywords import LEGAL_KEYWORDS, TOPIC_KEYWORDS, normalize_for_search

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

SOURCE_NAME = "Trang thông tin điện tử Cục Quản lý và Phát triển thị trường trong nước"
BASE_SITE_URL = "https://dms.gov.vn/"

DEFAULT_PREFIXES = [
    "https://dms.gov.vn/tin-t%E1%BB%A9c-s%E1%BB%B1-ki%E1%BB%87n",
    "https://dms.gov.vn/chinh-sach",
]
DEFAULT_ITEMS_PER_PAGE = 15
DEFAULT_PORTLET_ID = "com_soft_cms_view_listcategory_ViewListCategoryPortlet_INSTANCE_vfzg"
PREFIX_PORTLET_IDS = {
    "tin-tức-sự-kiện": "com_soft_cms_view_listcategory_ViewListCategoryPortlet_INSTANCE_vfzg",
    "chinh-sach": "com_soft_cms_view_listcategory_ViewListCategoryPortlet_INSTANCE_pbtf",
}

DATE_PATTERN = re.compile(
    r"\b(\d{2}/\d{2}/\d{4})(?:\s*(?:\||-|,)?\s*(\d{2}:\d{2})(?:\s*(?:AM|PM|SA|CH))?)?\b",
    re.IGNORECASE,
)

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
    response = session.get(url, timeout=REQUEST_TIMEOUT, verify=verify_ssl)
    response.raise_for_status()

    if not response.encoding or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding

    return response.text


def resolve_portlet_id(prefix: str) -> str:
    path = unquote(urlparse(prefix).path.strip("/"))
    slug = path.split("/")[-1] if path else ""
    return PREFIX_PORTLET_IDS.get(slug, DEFAULT_PORTLET_ID)


def build_listing_url(
    prefix: str,
    page_no: int,
    items_per_page: int = DEFAULT_ITEMS_PER_PAGE,
    portlet_id: Optional[str] = None,
) -> str:
    if page_no == 1 and items_per_page == DEFAULT_ITEMS_PER_PAGE and portlet_id is None:
        return prefix

    portlet_id = portlet_id or resolve_portlet_id(prefix)
    query = [
        ("p_p_id", portlet_id),
        ("p_p_lifecycle", "0"),
        ("p_p_state", "normal"),
        ("p_p_mode", "view"),
        (f"_{portlet_id}_resetCur", "false"),
        (f"_{portlet_id}_delta", str(items_per_page)),
        (f"_{portlet_id}_cur", str(page_no)),
    ]
    return f"{prefix}?{urlencode(query)}"


def try_parse_datetime(raw: Optional[str]) -> Optional[datetime]:
    raw_text = clean_text(raw)
    if not raw_text:
        return None

    match = DATE_PATTERN.search(raw_text)
    if match:
        raw_text = match.group(1)
        if match.group(2):
            raw_text = f"{raw_text} {match.group(2)}"

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


def extract_listing_date(node: BeautifulSoup) -> Optional[str]:
    time_node = node.select_one(".time")
    raw_text = time_node.get_text(" ") if time_node else node.get_text(" ")
    match = DATE_PATTERN.search(clean_text(raw_text))
    if not match:
        return None

    raw_date = match.group(1)
    if match.group(2):
        raw_date = f"{raw_date} {match.group(2)}"
    return format_datetime(raw_date)


def normalize_title(title: str) -> str:
    title = clean_text(title)
    suffixes = [
        " - Trang thông tin điện tử Cục Quản lý và Phát triển thị trường trong nước",
        " - Cục Quản lý và Phát triển thị trường trong nước",
    ]
    for suffix in suffixes:
        if title.endswith(suffix):
            return title[: -len(suffix)].strip()
    return title


def build_listing_article(
    node: BeautifulSoup,
    title_tag: BeautifulSoup,
    category_url: str,
) -> Optional[ParsedArticle]:
    title = clean_text(title_tag.get_text(" "))
    href = clean_text(title_tag.get("href"))

    if not title or not href or "/tin-chi-tiet/" not in href:
        return None

    summary_candidates = []
    for paragraph in node.find_all("p"):
        classes = paragraph.get("class") or []
        text = clean_text(paragraph.get_text(" "))
        if not text or text == title or "time" in classes or "title-item" in classes:
            continue
        if paragraph.find_parent("a") is title_tag or paragraph.find_parent("a") == title_tag:
            continue
        summary_candidates.append(text)

    return ParsedArticle(
        title=title,
        url=canonicalize_url(urljoin(BASE_SITE_URL, href)),
        source=SOURCE_NAME,
        published_at=extract_listing_date(node),
        summary_raw=clean_text(" ".join(summary_candidates)),
        category_url=category_url,
    )


def extract_listing_articles(html: str, category_url: str) -> list[ParsedArticle]:
    soup = BeautifulSoup(html, "html.parser")
    articles: list[ParsedArticle] = []
    seen_links: set[str] = set()

    for selector in [
        ".list-tin-part-1 .post-typical",
        ".list-tin-part-1 .title-item",
        ".list-tin-part-1 .list-bottom",
        ".list-tin-part-2 .li-item-list-tin_border-bottom",
    ]:
        for node in soup.select(selector):
            title_tag = node.select_one("a.title-list-tin-2[href]") or node.select_one("a[href]")
            if not title_tag:
                continue

            article = build_listing_article(node, title_tag, category_url)
            if not article or article.url in seen_links:
                continue

            seen_links.add(article.url)
            articles.append(article)

    return articles


def extract_title(soup: BeautifulSoup) -> str:
    for selector in [".entry-title", "h1", "h2"]:
        node = soup.select_one(selector)
        if node:
            title = clean_text(node.get_text(" "))
            if title:
                return normalize_title(title)

    og_title = extract_meta_content(soup, ("property", "og:title"), ("name", "title"))
    if og_title:
        return normalize_title(og_title)

    if soup.title:
        return normalize_title(soup.title.get_text(" "))

    return ""


def extract_published_at(soup: BeautifulSoup) -> Optional[str]:
    for selector in [
        ".entry-meta .more-info",
        ".entry-meta",
        "time",
    ]:
        node = soup.select_one(selector)
        if not node:
            continue

        parsed = format_datetime(node.get("datetime") if node.name == "time" else node.get_text(" "))
        if parsed:
            return parsed

    page_text = clean_text(soup.get_text(" "))
    match = DATE_PATTERN.search(page_text)
    if match:
        return format_datetime(match.group(0))

    return None


def extract_summary(soup: BeautifulSoup) -> str:
    summary_node = soup.select_one(".entry-summary")
    if summary_node:
        summary = clean_text(summary_node.get_text(" "))
        if summary:
            return summary

    return extract_meta_content(
        soup,
        ("name", "description"),
        ("property", "og:description"),
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


def crawl_dms(
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
    portlet_id: Optional[str] = None,
) -> list[dict]:
    """
    Main function để đưa vào hệ thống.

    Returns:
        list[dict] theo format:
        {
          "title": "...",
          "url": "...",
          "source": "Trang thông tin điện tử Cục Quản lý và Phát triển thị trường trong nước",
          "published_at": "2026-07-10 00:00",
          "summary_raw": "...",
          "category_url": "https://dms.gov.vn/..."
        }
    """
    logging.info("Start crawling DMS listings")

    if not verify_ssl:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    session = requests.Session()
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
                portlet_id=portlet_id,
            )

            try:
                logging.info("Fetching DMS prefix=%s page_no=%s", prefix, page_no)
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
        description="Crawl DMS and export legal/market-management updates as JSON."
    )
    parser.add_argument(
        "--prefixes",
        type=str,
        default=",".join(DEFAULT_PREFIXES),
        help="Danh sách prefix URL, ngăn cách bằng dấu phẩy. Mặc định: tin tức sự kiện và chính sách.",
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
        help="Số bài mỗi page. Mặc định: 15.",
    )
    parser.add_argument(
        "--max-pages-per-prefix",
        type=int,
        default=5,
        help="Số page tối đa cho mỗi prefix. Mặc định: 5.",
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
        "--verify-ssl",
        action="store_true",
        help="Bật xác thực SSL. Mặc định tắt vì dms.gov.vn có thể thiếu CA chain trong môi trường crawl.",
    )
    parser.add_argument(
        "--portlet-id",
        type=str,
        default=None,
        help="Override p_p_id nếu crawl một prefix DMS khác.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="dms_articles.json",
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

    articles = crawl_dms(
        prefixes=parse_prefixes(args.prefixes),
        days=None if args.days == 0 else args.days,
        max_articles=args.max_articles,
        items_per_page=args.items_per_page,
        max_pages_per_prefix=args.max_pages_per_prefix,
        filter_relevant=not args.no_filter,
        require_legal_keyword=True,
        require_topic_keyword=True,
        fetch_details=not args.no_detail,
        verify_ssl=args.verify_ssl,
        portlet_id=args.portlet_id,
    )

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)

    if args.pretty:
        print(json.dumps(articles, ensure_ascii=False, indent=2))

    print(f"Saved {len(articles)} articles to {args.output}")


if __name__ == "__main__":
    main()
