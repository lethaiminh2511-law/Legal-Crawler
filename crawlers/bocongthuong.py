from __future__ import annotations

import argparse
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from crawlers.common.keywords import LEGAL_KEYWORDS, TOPIC_KEYWORDS, normalize_for_search

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

SOURCE_NAME = "Cổng thông tin điện tử Bộ Công Thương"
BASE_SITE_URL = "https://moit.gov.vn/"
LISTING_URL = "https://moit.gov.vn/"

DEFAULT_CATEGORY_ID = "101788658"
DEFAULT_PARENT_ID = "101788658"
DEFAULT_MODULE_ID = "25"
DEFAULT_ITEMS_PER_PAGE = 12

DATE_PATTERN = re.compile(r"\b(\d{2}/\d{2}/\d{4})(?:\s+(\d{2}:\d{2}(?::\d{2})?))?\b")

HEADERS = {
    "accept": "*/*",
    "accept-language": "en,vi;q=0.9,en-US;q=0.8",
    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    "origin": "https://moit.gov.vn",
    "referer": "https://moit.gov.vn/tin-tuc",
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


def clean_text(text: Optional[str]) -> str:
    if not text:
        return ""
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fetch_html(session: requests.Session, url: str) -> str:
    response = session.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    if not response.encoding or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding

    return response.text


def fetch_listing_page(
    session: requests.Session,
    page_no: int,
    items_per_page: int,
    category_id: str = DEFAULT_CATEGORY_ID,
    parent_id: str = DEFAULT_PARENT_ID,
) -> str:
    params = [
        ("module", "Content.Listing"),
        ("moduleId", DEFAULT_MODULE_ID),
        ("cmd", "redraw"),
        ("site", "2005517"),
        ("url_mode", "rewrite"),
        ("submitFormId", DEFAULT_MODULE_ID),
        ("moduleId", DEFAULT_MODULE_ID),
        ("page", "Article.News.list"),
        ("site", "2005517"),
    ]
    data = {
        "layout": "Content.Article.News.default",
        "itemsPerPage": str(items_per_page),
        "orderB": "00publishTime DESC",
        "pageNo": str(page_no),
        "service": "Content.Article.selectAll",
        "widgetCode": "5b72a94b9218655475508114",
        "parentId": parent_id,
        "type": "Article.News",
        "categoryId": category_id,
        "widgetTemplateId": "5feffbc0cccf1c7cdf7dada3",
        "imageSizeRatio": "3:2",
        "hiddenAuthor": "1",
        "hiddenReadMore": "1",
        "page": "Article.News.list",
        "modulePosition": "0",
        "moduleParentId": "12",
        "phpModuleName": "Content.Listing",
        "_t": str(int(time.time() * 1000)),
    }

    response = session.post(
        LISTING_URL,
        params=params,
        data=data,
        timeout=REQUEST_TIMEOUT,
    )
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
        raw_text = match.group(1)
        if match.group(2):
            raw_text = f"{raw_text} {match.group(2)}"

    if raw_text.endswith("Z"):
        raw_text = raw_text[:-1] + "+0000"

    candidates = [
        "%d/%m/%Y %H:%M:%S",
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


def extract_listing_articles(html: str) -> list[ParsedArticle]:
    soup = BeautifulSoup(html, "html.parser")
    articles: list[ParsedArticle] = []

    for node in soup.select("article.article-news"):
        title_tag = node.select_one("a.article-title")
        if not title_tag:
            continue

        title = clean_text(title_tag.get_text(" ") or title_tag.get("title"))
        href = clean_text(title_tag.get("href"))
        if not title or not href:
            continue

        date_text = clean_text(node.select_one(".article-date").get_text(" ") if node.select_one(".article-date") else "")
        summary = clean_text(node.select_one(".article-brief").get_text(" ") if node.select_one(".article-brief") else "")

        articles.append(
            ParsedArticle(
                title=title,
                url=urljoin(BASE_SITE_URL, href.lstrip("/")),
                source=SOURCE_NAME,
                published_at=format_datetime(date_text),
                summary_raw=summary,
            )
        )

    return articles


def extract_title(soup: BeautifulSoup) -> str:
    h1 = soup.find("h1")
    if h1:
        title = clean_text(h1.get_text(" "))
        if title:
            return title

    og_title = extract_meta_content(soup, ("property", "og:title"), ("name", "title"))
    if og_title:
        return og_title

    if soup.title:
        return clean_text(soup.title.get_text(" "))

    return ""


def extract_published_at(soup: BeautifulSoup) -> Optional[str]:
    meta_date = extract_meta_content(
        soup,
        ("property", "article:published_time"),
        ("itemprop", "datePublished"),
        ("itemprop", "dateCreated"),
        ("name", "DC.Date"),
    )
    if meta_date:
        parsed = try_parse_datetime(meta_date)
        if parsed:
            return parsed.strftime("%Y-%m-%d %H:%M")

    time_tag = soup.find("time")
    if time_tag:
        parsed = try_parse_datetime(time_tag.get("datetime") or time_tag.get_text(" "))
        if parsed:
            return parsed.strftime("%Y-%m-%d %H:%M")

    page_text = clean_text(soup.get_text(" "))
    match = DATE_PATTERN.search(page_text)
    if match:
        parsed = try_parse_datetime(match.group(0))
        if parsed:
            return parsed.strftime("%Y-%m-%d %H:%M")

    return None


def extract_summary(soup: BeautifulSoup) -> str:
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


def article_to_json_dict(article: ParsedArticle) -> dict:
    return {
        "title": article.title,
        "url": article.url,
        "source": article.source,
        "published_at": article.published_at,
        "summary_raw": article.summary_raw,
    }


def crawl_bo_cong_thuong(
    days: Optional[int] = 1,
    max_articles: int = 50,
    items_per_page: int = DEFAULT_ITEMS_PER_PAGE,
    max_pages: int = 10,
    category_id: str = DEFAULT_CATEGORY_ID,
    parent_id: str = DEFAULT_PARENT_ID,
    filter_relevant: bool = True,
    require_legal_keyword: bool = True,
    require_topic_keyword: bool = True,
    fetch_details: bool = True,
) -> list[dict]:
    """
    Main function để đưa vào hệ thống.

    Returns:
        list[dict] theo format:
        {
          "title": "...",
          "url": "...",
          "source": "Cổng thông tin điện tử Bộ Công Thương",
          "published_at": "2026-06-26 10:41",
          "summary_raw": "..."
        }
    """
    logging.info("Start crawling Bo Cong Thuong listing")

    session = requests.Session()
    session.headers.update(HEADERS)

    results: list[dict] = []
    seen_links: set[str] = set()

    for page_no in range(1, max_pages + 1):
        if len(results) >= max_articles:
            break

        try:
            logging.info("Fetching MOIT page_no=%s items_per_page=%s", page_no, items_per_page)
            html = fetch_listing_page(
                session=session,
                page_no=page_no,
                items_per_page=items_per_page,
                category_id=category_id,
                parent_id=parent_id,
            )
            listing_articles = extract_listing_articles(html)

            if not listing_articles:
                logging.info("No articles found on page_no=%s", page_no)
                break

            should_stop = False

            for listing_article in listing_articles:
                if len(results) >= max_articles:
                    break

                if is_older_than_window(listing_article.published_at, days):
                    logging.info("Stop at old article date: %s", listing_article.title)
                    should_stop = True
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

            if should_stop:
                break

            time.sleep(POLITE_DELAY_SECONDS)

            if len(listing_articles) < items_per_page:
                break

        except Exception as exc:
            logging.warning("Failed page_no=%s: %s", page_no, exc)
            break

    logging.info("Finished. Parsed %d relevant articles.", len(results))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crawl Bo Cong Thuong and export legal/IP-tech updates as JSON."
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
        help="Số bài mỗi page API. Mặc định: 12.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=10,
        help="Số page tối đa. Mặc định: 10.",
    )
    parser.add_argument(
        "--category-id",
        type=str,
        default=DEFAULT_CATEGORY_ID,
        help="categoryId truyền vào endpoint. Mặc định: 101788658 (/tin-tuc).",
    )
    parser.add_argument(
        "--parent-id",
        type=str,
        default=DEFAULT_PARENT_ID,
        help="parentId truyền vào endpoint. Mặc định: 101788658 (/tin-tuc).",
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
        default="bocongthuong_articles.json",
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

    articles = crawl_bo_cong_thuong(
        days=None if args.days == 0 else args.days,
        max_articles=args.max_articles,
        items_per_page=args.items_per_page,
        max_pages=args.max_pages,
        category_id=args.category_id,
        parent_id=args.parent_id,
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
