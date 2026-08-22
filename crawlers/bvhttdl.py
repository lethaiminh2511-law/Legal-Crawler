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

import requests
from bs4 import BeautifulSoup, Tag

from crawlers.common.dates import VN_TZ, format_datetime, is_within_days
from crawlers.common.http import fetch_html
from crawlers.common.io import write_json
from crawlers.common.keywords import is_relevant_text
from crawlers.common.text import clean_text


SOURCE_NAME = "Cổng thông tin điện tử Bộ Văn hóa, Thể thao và Du lịch"
BASE_SITE_URL = "https://bvhttdl.gov.vn/"
DEFAULT_SECTIONS = ("van-ban-du-thao", "van-ban-quan-ly")

REQUEST_TIMEOUT = 25
FETCH_RETRIES = 2
POLITE_DELAY_SECONDS = 0.8

DATE_PATTERN = re.compile(
    r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{4})(?:\s+(\d{1,2}:\d{2}(?::\d{2})?))?\b"
)
DRAFT_DEADLINE_PATTERN = re.compile(
    r"(?:Thời\s*hạn|Hạn\s*góp\s*ý)\s*:?\s*"
    r"(?P<start>\d{1,2}[/-]\d{1,2}[/-]\d{4})"
    r"(?:\s*(?:-|đến|–)\s*(?P<end>\d{1,2}[/-]\d{1,2}[/-]\d{4}))?",
    re.IGNORECASE,
)
DOCUMENT_PATH_PATTERN = re.compile(
    r"^/(?:van-ban-du-thao/.+\.htm|y-kien-cho-van-ban-du-thao|"
    r"van-ban-quan-ly/\d+\.htm|van-ban-chi-tiet)$",
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


@dataclass
class ParsedBvhttdlArticle:
    title: str
    url: str
    source: str
    published_at: Optional[str]
    summary_raw: str
    category: str
    category_url: str
    document_type: str = ""
    deadline_start: Optional[str] = None
    deadline_end: Optional[str] = None
    issuing_agency: str = ""
    document_number: str = ""


def parse_sections(raw: str) -> list[str]:
    return [item.strip().strip("/") for item in raw.split(",") if item.strip()]


def build_listing_page_url(section: str, page: int) -> str:
    return urljoin(BASE_SITE_URL, section.strip("/")) + f"?Page={page}"


def normalize_date(raw_date: Optional[str]) -> Optional[str]:
    raw_text = clean_text(raw_date)
    if not raw_text:
        return None

    match = DATE_PATTERN.search(raw_text)
    if match:
        date_text = match.group(1).replace("-", "/")
        time_text = match.group(2) or "00:00"
        return format_datetime(f"{date_text} {time_text}")

    return format_datetime(raw_text)


def normalize_target_date(raw_date: Optional[str]) -> str:
    if not raw_date:
        return datetime.now(VN_TZ).strftime("%d-%m-%Y")

    raw_text = clean_text(raw_date)
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw_text, fmt).strftime("%d-%m-%Y")
        except ValueError:
            continue

    raise ValueError("Date must be dd-mm-yyyy, dd/mm/yyyy, yyyy-mm-dd, or yyyy/mm/dd")


def get_target_dates(
    days: Optional[int] = 1,
    target_date: Optional[str] = None,
    now: Optional[datetime] = None,
) -> list[str]:
    if target_date:
        return [normalize_target_date(target_date)]

    if days is None:
        return []

    current = now or datetime.now(VN_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=VN_TZ)

    day_count = max(days, 1)
    end_date = current.astimezone(VN_TZ).date()
    start_date = end_date - timedelta(days=day_count - 1)
    return [
        (start_date + timedelta(days=offset)).strftime("%d-%m-%Y")
        for offset in range(day_count)
    ]


def is_bvhttdl_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.netloc.endswith("bvhttdl.gov.vn")


def is_document_url(url: str) -> bool:
    parsed = urlparse(url)
    if not is_bvhttdl_url(url):
        return False
    if parsed.path == "/van-ban-chi-tiet":
        return "vbid=" in parsed.query
    return bool(DOCUMENT_PATH_PATTERN.match(parsed.path))


def normalize_document_url(page_url: str, href: str) -> str:
    absolute_url = urljoin(page_url, clean_text(href)).split("#")[0].strip()
    return absolute_url


def extract_article_links(html: str, page_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []

    for tag in soup.find_all("a", href=True):
        absolute_url = normalize_document_url(page_url, tag.get("href", ""))
        if is_document_url(absolute_url):
            links.append(absolute_url)

    seen: set[str] = set()
    unique_links: list[str] = []
    for link in links:
        if link in seen:
            continue
        seen.add(link)
        unique_links.append(link)

    return unique_links


def extract_meta_content(soup: BeautifulSoup, *selectors: tuple[str, str]) -> str:
    for attr_name, attr_value in selectors:
        tag = soup.find("meta", attrs={attr_name: attr_value})
        if tag and tag.get("content"):
            return clean_text(tag.get("content"))
    return ""


def extract_title(soup: BeautifulSoup) -> str:
    selectors = [
        "h1",
        ".detail-title",
        ".article-title",
        ".news-title",
        ".title-detail",
        ".gyk-title",
    ]

    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            title = clean_text(node.get_text(" "))
            if title:
                return title

    meta_title = extract_meta_content(
        soup,
        ("property", "og:title"),
        ("name", "title"),
    )
    if meta_title:
        return meta_title.replace("Bộ Văn hóa, Thể thao và Du lịch", "").strip(" -")

    if soup.title:
        return clean_text(soup.title.get_text(" ")).replace(
            "Bộ Văn hóa, Thể thao và Du lịch", ""
        ).strip(" -")

    return ""


def meaningful_value(value: str) -> str:
    cleaned = clean_text(value)
    if cleaned in {"", "-", "--"}:
        return ""
    return cleaned


def is_placeholder_title(title: str) -> bool:
    normalized = clean_text(title).lower()
    return normalized in {"van-ban-chi-tiet", "van ban chi tiet", "chi tiết văn bản"}


def extract_summary(soup: BeautifulSoup) -> str:
    meta_description = extract_meta_content(
        soup,
        ("name", "description"),
        ("property", "og:description"),
    )
    if meta_description:
        return meta_description

    for selector in [
        ".summary",
        ".sapo",
        ".article-sapo",
        ".detail-sapo",
        ".document-summary",
        ".content",
        ".detail-content",
    ]:
        node = soup.select_one(selector)
        if node:
            text = clean_text(node.get_text(" "))
            if text:
                return text

    return ""


def extract_labeled_value(soup: BeautifulSoup, label: str) -> str:
    normalized_label = clean_text(label).lower()
    fields = ["dt", "td", "th", "label", "span", "div", "strong", "b"]

    for node in soup.find_all(fields):
        node_text = clean_text(node.get_text(" "))
        if node_text.lower().rstrip(":") != normalized_label.lower().rstrip(":"):
            continue

        sibling = node.find_next_sibling(["dd", "td", "div", "span", "p"])
        if sibling:
            value = clean_text(sibling.get_text(" "))
            if value:
                return meaningful_value(value)

    page_text = clean_text(soup.get_text(" "))
    stop_labels = (
        "Số hiệu|Cơ quan ban hành|Loại văn bản|Hình thức văn bản|"
        "Ngày ban hành|Ngày có hiệu lực|Trích yếu|Nội dung|Tệp đính kèm|Thời hạn"
    )
    pattern = re.compile(
        rf"{re.escape(label)}\s*:?\s*(.+?)(?=\s+(?:{stop_labels})\s*:|\s*$)",
        re.IGNORECASE,
    )
    match = pattern.search(page_text)
    return meaningful_value(match.group(1)) if match else ""


def extract_deadline_dates(text: str) -> tuple[Optional[str], Optional[str]]:
    match = DRAFT_DEADLINE_PATTERN.search(clean_text(text))
    if not match:
        return None, None

    return normalize_date(match.group("start")), normalize_date(match.group("end"))


def find_nearest_deadline_text(node: Tag) -> str:
    for candidate in [node, *node.parents]:
        if getattr(candidate, "name", None) == "[document]":
            break
        text = clean_text(candidate.get_text(" "))
        if DRAFT_DEADLINE_PATTERN.search(text):
            return text
    return ""


def find_nearest_date_text(node: Tag) -> str:
    for candidate in [node, *node.parents]:
        if getattr(candidate, "name", None) == "[document]":
            break
        text = clean_text(candidate.get_text(" "))
        match = DATE_PATTERN.search(text)
        if match:
            return match.group(0)
    return ""


def infer_category(section: str, url: str) -> str:
    if section == "van-ban-quan-ly" or "/van-ban-quan-ly/" in url:
        return "Văn bản quản lý"
    return "Văn bản dự thảo"


def infer_document_type(category: str, title: str, soup: Optional[BeautifulSoup] = None) -> str:
    if soup:
        for label in ("Loại văn bản", "Hình thức văn bản"):
            value = extract_labeled_value(soup, label)
            if value:
                return value

    lowered = clean_text(title).lower()
    for document_type in ("nghị định", "thông tư", "quyết định", "nghị quyết", "luật"):
        if document_type in lowered:
            return document_type.title()

    return "Dự thảo" if "dự thảo" in category.lower() else ""


def extract_listing_articles(html: str, page_url: str, section: str) -> list[ParsedBvhttdlArticle]:
    soup = BeautifulSoup(html, "html.parser")
    articles_by_url: dict[str, ParsedBvhttdlArticle] = {}

    for link in soup.find_all("a", href=True):
        url = normalize_document_url(page_url, link.get("href", ""))
        if not is_document_url(url):
            continue

        title = clean_text(link.get_text(" "))
        if not title:
            continue

        date_text = find_nearest_date_text(link)
        category = infer_category(section, url)
        deadline_start, deadline_end = (None, None)
        if "dự thảo" in category.lower():
            deadline_start, deadline_end = extract_deadline_dates(find_nearest_deadline_text(link))

        article = ParsedBvhttdlArticle(
            title=title,
            url=url,
            source=SOURCE_NAME,
            published_at=deadline_start or normalize_date(date_text),
            summary_raw=title,
            category=category,
            category_url=page_url,
            document_type=infer_document_type(category, title),
            deadline_start=deadline_start,
            deadline_end=deadline_end,
        )

        existing = articles_by_url.get(url)
        if not existing or len(article.title) > len(existing.title):
            if existing and not article.published_at:
                article.published_at = existing.published_at
            articles_by_url[url] = article

    return list(articles_by_url.values())


def enrich_article_from_detail(article: ParsedBvhttdlArticle, html: str) -> ParsedBvhttdlArticle:
    soup = BeautifulSoup(html, "html.parser")
    page_text = clean_text(soup.get_text(" "))

    detail_title = extract_title(soup)
    title = article.title if is_placeholder_title(detail_title) else detail_title or article.title
    summary = extract_summary(soup) or article.summary_raw
    deadline_start, deadline_end = extract_deadline_dates(page_text)

    issued_date = (
        extract_labeled_value(soup, "Ngày ban hành")
        or extract_labeled_value(soup, "Ngày đăng")
        or extract_labeled_value(soup, "Ngày hiệu lực")
    )
    published_at = (
        deadline_start
        or normalize_date(issued_date)
        or article.published_at
        or normalize_date(page_text)
    )

    return ParsedBvhttdlArticle(
        title=title,
        url=article.url,
        source=article.source,
        published_at=published_at,
        summary_raw=summary,
        category=article.category,
        category_url=article.category_url,
        document_type=infer_document_type(article.category, title, soup) or article.document_type,
        deadline_start=deadline_start or article.deadline_start,
        deadline_end=deadline_end or article.deadline_end,
        issuing_agency=extract_labeled_value(soup, "Cơ quan ban hành"),
        document_number=extract_labeled_value(soup, "Số hiệu")
        or extract_labeled_value(soup, "Số / ký hiệu"),
    )


def is_on_target_date(article: ParsedBvhttdlArticle, target_dates: list[str]) -> bool:
    if not target_dates:
        return True

    parsed = format_datetime(article.published_at)
    if not parsed:
        return True

    article_date = datetime.strptime(parsed, "%Y-%m-%d %H:%M").strftime("%d-%m-%Y")
    if article_date in target_dates:
        return True

    if article.deadline_start and article.deadline_end:
        start = datetime.strptime(article.deadline_start, "%Y-%m-%d %H:%M").date()
        end = datetime.strptime(article.deadline_end, "%Y-%m-%d %H:%M").date()
        for target_date in target_dates:
            target = datetime.strptime(target_date, "%d-%m-%Y").date()
            if start <= target <= end:
                return True

    return False


def is_relevant_article(
    article: ParsedBvhttdlArticle,
    require_legal_keyword: bool = True,
    require_topic_keyword: bool = True,
) -> bool:
    searchable = " ".join(
        [
            article.title,
            article.summary_raw,
            article.category,
            article.document_type,
            article.issuing_agency,
            article.document_number,
        ]
    )
    require_topic = require_topic_keyword
    if "/y-kien-cho-van-ban-du-thao" in article.url:
        require_topic = False

    return is_relevant_text(
        searchable,
        require_legal_keyword=require_legal_keyword,
        require_topic_keyword=require_topic,
    )


def article_to_json_dict(article: ParsedBvhttdlArticle) -> dict[str, Optional[str]]:
    return {
        "title": article.title,
        "url": article.url,
        "source": article.source,
        "published_at": article.published_at,
        "summary_raw": article.summary_raw,
        "category": article.category,
        "category_url": article.category_url,
        "document_type": article.document_type,
        "deadline_start": article.deadline_start,
        "deadline_end": article.deadline_end,
        "issuing_agency": article.issuing_agency,
        "document_number": article.document_number,
    }


def crawl_bo_van_hoa_the_thao_du_lich(
    sections: Optional[list[str]] = None,
    days: Optional[int] = 1,
    target_date: Optional[str] = None,
    max_articles: int = 50,
    max_pages: int = 5,
    filter_relevant: bool = True,
    require_legal_keyword: bool = True,
    require_topic_keyword: bool = True,
    now: Optional[datetime] = None,
) -> list[dict[str, Optional[str]]]:
    session = requests.Session()
    session.headers.update(HEADERS)

    target_dates = get_target_dates(days=days, target_date=target_date, now=now)
    results: list[dict[str, Optional[str]]] = []
    seen_urls: set[str] = set()

    for section in sections or list(DEFAULT_SECTIONS):
        for page_no in range(1, max_pages + 1):
            if len(results) >= max_articles:
                break

            listing_url = build_listing_page_url(section, page_no)
            try:
                listing_html = fetch_html(
                    session,
                    listing_url,
                    timeout=REQUEST_TIMEOUT,
                    retries=FETCH_RETRIES,
                    delay_seconds=POLITE_DELAY_SECONDS,
                )
            except Exception as exc:
                logging.warning("Failed listing page %s: %s", listing_url, exc)
                break

            listing_articles = extract_listing_articles(listing_html, listing_url, section)
            if not listing_articles:
                break

            for article in listing_articles:
                if len(results) >= max_articles:
                    break
                if article.url in seen_urls:
                    continue
                seen_urls.add(article.url)

                if (
                    not target_date
                    and article.published_at
                    and not is_within_days(article.published_at, days, now=now)
                ):
                    continue

                try:
                    detail_html = fetch_html(
                        session,
                        article.url,
                        timeout=REQUEST_TIMEOUT,
                        retries=FETCH_RETRIES,
                        delay_seconds=POLITE_DELAY_SECONDS,
                    )
                    article = enrich_article_from_detail(article, detail_html)
                    time.sleep(POLITE_DELAY_SECONDS)
                except Exception as exc:
                    logging.warning("Failed detail page %s: %s", article.url, exc)

                if target_date and not is_on_target_date(article, target_dates):
                    continue
                if not target_date and not is_within_days(article.published_at, days, now=now):
                    continue

                if filter_relevant and not is_relevant_article(
                    article,
                    require_legal_keyword=require_legal_keyword,
                    require_topic_keyword=require_topic_keyword,
                ):
                    continue

                results.append(article_to_json_dict(article))

    logging.info("Finished. Parsed %d relevant Bvhttdl articles.", len(results))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crawl Bộ Văn hóa, Thể thao và Du lịch legal documents as JSON."
    )
    parser.add_argument(
        "--sections",
        type=str,
        default=",".join(DEFAULT_SECTIONS),
        help="Comma-separated section slugs.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=1,
        help="Only include items from the last N days. Use --days 0 to disable.",
    )
    parser.add_argument(
        "--target-date",
        type=str,
        default=None,
        help="Optional exact target date, e.g. 18-07-2026.",
    )
    parser.add_argument(
        "--max-articles",
        type=int,
        default=50,
        help="Maximum number of articles to return. Default: 50.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=5,
        help="Maximum listing pages per section. Default: 5.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="bvhttdl_articles.json",
        help="JSON output file.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Print formatted JSON to stdout.",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    articles = crawl_bo_van_hoa_the_thao_du_lich(
        sections=parse_sections(args.sections),
        days=None if args.days == 0 else args.days,
        target_date=args.target_date,
        max_articles=args.max_articles,
        max_pages=args.max_pages,
        filter_relevant=True,
        require_legal_keyword=True,
        require_topic_keyword=True,
    )

    write_json(articles, args.output)

    if args.pretty:
        print(json.dumps(articles, ensure_ascii=False, indent=2))

    print(f"Saved {len(articles)} articles to {args.output}")


if __name__ == "__main__":
    main()
