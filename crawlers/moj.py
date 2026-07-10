from __future__ import annotations

import argparse
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urljoin, urlparse, urlunparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup, Tag

from crawlers.common.keywords import LEGAL_KEYWORDS, TOPIC_KEYWORDS

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

SOURCE_NAME = "Cổng thông tin điện tử Bộ Tư pháp"
BASE_SITE_URL = "https://moj.gov.vn/"

DEFAULT_PREFIXES = [
    "https://moj.gov.vn/portal/tin-tuc/chuyen-muc/chi-dao-dieu-hanh-cua-lanh-dao-bo.html",
    "https://moj.gov.vn/portal/tin-tuc/chuyen-muc/van-ban-chinh-sach-moi.html",
]

DATE_PATTERN = re.compile(
    r"\b(\d{2}/\d{2}/\d{4}|\d{2}-\d{2}-\d{4})(?:\s+(\d{2}:\d{2}(?::\d{2})?))?\b"
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


def clean_text(text: Optional[object]) -> str:
    if text is None:
        return ""
    text = str(text).replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_for_search(text: str) -> str:
    return clean_text(text).lower()


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(query="", fragment=""))


def fetch_html(session: requests.Session, url: str) -> str:
    response = session.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    if not response.encoding or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding

    return response.text


def is_moj_article_url(url: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.netloc.endswith("moj.gov.vn")
        and "/portal/tin-tuc/chi-tiet/" in parsed.path
        and parsed.path.endswith(".html")
    )


def try_parse_datetime(raw: Optional[object]) -> Optional[datetime]:
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


def format_datetime(raw: Optional[object]) -> Optional[str]:
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


def find_article_container(link: Tag) -> Tag:
    current = link
    for _ in range(6):
        parent = current.parent
        if not isinstance(parent, Tag):
            break
        if parent.name in {"body", "html"}:
            break
        text = clean_text(parent.get_text(" "))
        if DATE_PATTERN.search(text) and parent.find("a", href=True):
            return parent
        current = parent
    return link.parent if isinstance(link.parent, Tag) else link


def extract_listing_date(node: Tag) -> Optional[str]:
    match = DATE_PATTERN.search(clean_text(node.get_text(" ")))
    if not match:
        return None

    return format_datetime(" ".join(part for part in match.groups() if part))


def extract_listing_summary(node: Tag, title: str) -> str:
    for selector in ["p", ".summary", ".sapo", ".description", ".desc"]:
        summary_node = node.select_one(selector)
        if not summary_node:
            continue
        summary = clean_text(summary_node.get_text(" "))
        if summary and summary != title and not DATE_PATTERN.fullmatch(summary):
            return summary
    return ""


def extract_listing_articles(html: str, category_url: str) -> list[ParsedArticle]:
    soup = BeautifulSoup(html, "html.parser")
    articles: list[ParsedArticle] = []
    seen_links: set[str] = set()

    for link in soup.find_all("a", href=True):
        href = clean_text(link.get("href"))
        url = canonicalize_url(urljoin(BASE_SITE_URL, href))
        if not is_moj_article_url(url) or url in seen_links:
            continue

        title = clean_text(link.get_text(" "))
        if not title:
            continue

        container = find_article_container(link)
        published_at = extract_listing_date(container)
        if not published_at:
            continue

        seen_links.add(url)

        articles.append(
            ParsedArticle(
                title=title,
                url=url,
                source=SOURCE_NAME,
                published_at=published_at,
                summary_raw=extract_listing_summary(container, title),
                category_url=category_url,
            )
        )

    return articles


def extract_title(soup: BeautifulSoup) -> str:
    for selector in ["h1", ".detail-title", ".article-title", ".news-title", "h2"]:
        node = soup.select_one(selector)
        if node:
            title = clean_text(node.get_text(" "))
            if title:
                return title

    og_title = extract_meta_content(soup, ("property", "og:title"), ("name", "title"))
    if og_title:
        return og_title.replace(" - Cổng thông tin điện tử Bộ Tư pháp", "").strip()

    if soup.title:
        return clean_text(soup.title.get_text(" ")).replace(
            " - Cổng thông tin điện tử Bộ Tư pháp", ""
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
    parsed = format_datetime(meta_date)
    if parsed:
        return parsed

    time_tag = soup.find("time")
    if time_tag:
        parsed = format_datetime(time_tag.get("datetime") or time_tag.get_text(" "))
        if parsed:
            return parsed

    for selector in [
        ".date",
        ".time",
        ".detail-time",
        ".article-date",
        ".news-date",
        ".publish-date",
    ]:
        node = soup.select_one(selector)
        if node:
            parsed = format_datetime(node.get_text(" "))
            if parsed:
                return parsed

    page_text = clean_text(soup.get_text(" "))
    match = DATE_PATTERN.search(page_text)
    if match:
        return format_datetime(match.group(0))

    return None


def extract_summary(soup: BeautifulSoup) -> str:
    meta_description = extract_meta_content(
        soup,
        ("name", "description"),
        ("property", "og:description"),
        ("name", "DC.Description"),
    )
    if meta_description:
        return meta_description

    for selector in [".sapo", ".summary", ".lead", ".article-sapo", ".detail-sapo"]:
        node = soup.select_one(selector)
        if node:
            summary = clean_text(node.get_text(" "))
            if summary:
                return summary

    return ""


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


def get_start_date(
    days: Optional[int],
    now: Optional[datetime] = None,
) -> Optional[datetime.date]:
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


def extract_next_listing_url(
    html: str,
    current_url: str,
    current_page_no: int,
) -> Optional[str]:
    soup = BeautifulSoup(html, "html.parser")
    wanted_page = str(current_page_no + 1)

    for link in soup.find_all("a", href=True):
        text = clean_text(link.get_text(" "))
        if text not in {wanted_page, "Tiếp", "Sau", "Next", ">"}:
            continue

        url = canonicalize_url(urljoin(current_url, clean_text(link.get("href"))))
        parsed = urlparse(url)
        if parsed.netloc.endswith("moj.gov.vn") and "/portal/tin-tuc/chuyen-muc/" in parsed.path:
            return url

    return None


def article_to_json_dict(article: ParsedArticle) -> dict:
    return {
        "title": article.title,
        "url": article.url,
        "source": article.source,
        "published_at": article.published_at,
        "summary_raw": article.summary_raw,
        "category_url": article.category_url,
    }


def crawl_moj(
    prefixes: Optional[list[str]] = None,
    days: Optional[int] = 1,
    max_articles: int = 50,
    max_pages_per_prefix: int = 5,
    filter_relevant: bool = True,
    require_legal_keyword: bool = True,
    require_topic_keyword: bool = True,
    fetch_details: bool = True,
) -> list[dict]:
    """
    Main function de dua vao he thong.

    Returns:
        list[dict] theo format:
        {
          "title": "...",
          "url": "...",
          "source": "Cổng thông tin điện tử Bộ Tư pháp",
          "published_at": "2026-06-24 00:00",
          "summary_raw": "...",
          "category_url": "https://moj.gov.vn/..."
        }
    """
    logging.info("Start crawling MOJ listings")

    session = requests.Session()
    session.headers.update(HEADERS)

    results: list[dict] = []
    seen_links: set[str] = set()

    for prefix in prefixes or DEFAULT_PREFIXES:
        logging.info("Start prefix=%s", prefix)
        listing_url: Optional[str] = prefix

        for page_no in range(1, max_pages_per_prefix + 1):
            if len(results) >= max_articles or not listing_url:
                break

            try:
                logging.info("Fetching MOJ prefix=%s page_no=%s", prefix, page_no)
                html = fetch_html(session, listing_url)
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
                            detail_html = fetch_html(session, listing_article.url)
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
                listing_url = extract_next_listing_url(html, listing_url, page_no)

            except Exception as exc:
                logging.warning("Failed prefix=%s page_no=%s: %s", prefix, page_no, exc)
                break

    logging.info("Finished. Parsed %d relevant articles.", len(results))
    return results


def parse_prefixes(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crawl MOJ and export legal/policy updates as JSON."
    )
    parser.add_argument(
        "--prefixes",
        type=str,
        default=",".join(DEFAULT_PREFIXES),
        help="Danh sach prefix URL, ngan cach bang dau phay. Mac dinh: 2 chuyen muc MOJ da yeu cau.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=1,
        help="Chi lay bai trong N ngay theo lich gan nhat. Mac dinh: 1 la hom nay. Dung --days 0 de bo loc ngay.",
    )
    parser.add_argument(
        "--max-articles",
        type=int,
        default=50,
        help="So bai toi da tra ve. Mac dinh: 50.",
    )
    parser.add_argument(
        "--max-pages-per-prefix",
        type=int,
        default=5,
        help="So page toi da cho moi prefix. Mac dinh: 5.",
    )
    parser.add_argument(
        "--no-filter",
        action="store_true",
        help="Khong loc keyword; lay tat ca bai tim duoc.",
    )
    parser.add_argument(
        "--no-detail",
        action="store_true",
        help="Khong fetch tung trang chi tiet; chi dung du lieu listing.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="moj_articles.json",
        help="File JSON output.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="In JSON dep ra man hinh.",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    articles = crawl_moj(
        prefixes=parse_prefixes(args.prefixes),
        days=None if args.days == 0 else args.days,
        max_articles=args.max_articles,
        max_pages_per_prefix=args.max_pages_per_prefix,
        filter_relevant=not args.no_filter,
        require_legal_keyword=True,
        require_topic_keyword=True,
        fetch_details=not args.no_detail,
    )

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)

    if args.pretty:
        print(json.dumps(articles, ensure_ascii=False, indent=2))

    print(f"Saved {len(articles)} articles to {args.output}")


if __name__ == "__main__":
    main()
