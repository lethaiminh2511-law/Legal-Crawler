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
DRAFT_LISTING_URL = "https://moit.gov.vn/du-thao-van-ban"

DEFAULT_CATEGORY_ID = "101788658"
DEFAULT_PARENT_ID = "101788658"
DEFAULT_MODULE_ID = "25"
DEFAULT_ITEMS_PER_PAGE = 12

DATE_PATTERN = re.compile(r"\b(\d{2}/\d{2}/\d{4})(?:\s+(\d{2}:\d{2}(?::\d{2})?))?\b")
DRAFT_DATES_PATTERN = re.compile(
    r"Ngày\s*bắt\s*đầu\s*:\s*(?P<start>\d{2}/\d{2}/\d{4})\s*-\s*"
    r"Ngày\s*hết\s*hạn\s*:\s*(?P<end>\d{2}/\d{2}/\d{4})?",
    re.IGNORECASE,
)

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


@dataclass(frozen=True)
class ListingSource:
    module_id: str
    submit_form_id: str
    page: str
    layout: str
    order_field: str
    order_value: str
    widget_code: str
    parent_id: str
    article_type: str
    category_id: str
    widget_template_id: str
    image_size_ratio: str
    module_position: str
    module_parent_id: str
    extra_fields: Optional[str] = None
    block_vb: Optional[str] = None
    hidden_author: Optional[str] = None
    hidden_read_more: Optional[str] = None
    php_module_name: Optional[str] = None


def build_news_listing_source(category_id: str, parent_id: str) -> ListingSource:
    return ListingSource(
        module_id=DEFAULT_MODULE_ID,
        submit_form_id=DEFAULT_MODULE_ID,
        page="Article.News.list",
        layout="Content.Article.News.default",
        order_field="orderB",
        order_value="00publishTime DESC",
        widget_code="5b72a94b9218655475508114",
        parent_id=parent_id,
        article_type="Article.News",
        category_id=category_id,
        widget_template_id="5feffbc0cccf1c7cdf7dada3",
        image_size_ratio="3:2",
        module_position="0",
        module_parent_id="12",
        hidden_author="1",
        hidden_read_more="1",
        php_module_name="Content.Listing",
    )


LEGAL_DOCUMENT_LISTING_SOURCE = ListingSource(
    module_id="12",
    submit_form_id="12",
    page="Article.LegalDocument.list",
    layout="Content.Article.LegalDocument.default",
    order_field="orderBy",
    order_value="publishTime DESC",
    widget_code="5b73e3f1921865098125edb5",
    parent_id="101788669",
    article_type="Article.LegalDocument",
    category_id="101788669",
    widget_template_id="5ff43820517c7b17487e1572",
    image_size_ratio="16:9",
    module_position="10",
    module_parent_id="7",
    extra_fields="code",
    block_vb="1",
)


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


def build_draft_listing_page_url(page_no: int) -> str:
    if page_no <= 1:
        return DRAFT_LISTING_URL
    return f"{DRAFT_LISTING_URL}?page={page_no}"


def fetch_listing_page(
    session: requests.Session,
    page_no: int,
    items_per_page: int,
    category_id: str = DEFAULT_CATEGORY_ID,
    parent_id: str = DEFAULT_PARENT_ID,
    listing_source: Optional[ListingSource] = None,
) -> str:
    source = listing_source or build_news_listing_source(category_id, parent_id)
    params = [
        ("module", "Content.Listing"),
        ("moduleId", source.module_id),
        ("cmd", "redraw"),
        ("site", "2005517"),
        ("url_mode", "rewrite"),
        ("submitFormId", source.submit_form_id),
        ("page", source.page),
        ("site", "2005517"),
    ]
    data = {
        "layout": source.layout,
        "itemsPerPage": str(items_per_page),
        source.order_field: source.order_value,
        "pageNo": str(page_no),
        "service": "Content.Article.selectAll",
        "widgetCode": source.widget_code,
        "parentId": source.parent_id,
        "type": source.article_type,
        "categoryId": source.category_id,
        "widgetTemplateId": source.widget_template_id,
        "imageSizeRatio": source.image_size_ratio,
        "page": source.page,
        "modulePosition": source.module_position,
        "moduleParentId": source.module_parent_id,
        "_t": str(int(time.time() * 1000)),
    }
    optional_fields = {
        "extraFields": source.extra_fields,
        "blockVB": source.block_vb,
        "hiddenAuthor": source.hidden_author,
        "hiddenReadMore": source.hidden_read_more,
        "phpModuleName": source.php_module_name,
    }
    data.update({key: value for key, value in optional_fields.items() if value is not None})

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

    listing_nodes = soup.select("article.article-news, .document-item, .article-item, li.article-news, tr")

    for node in listing_nodes:
        title_tag = node.select_one(
            "a.article-title, a.document-title, a.legal-title, "
            'a[href*="/van-ban-phap-luat/"], a[href*="/tin-tuc/"], a[href]'
        )
        if not title_tag:
            continue

        title = clean_text(title_tag.get_text(" ") or title_tag.get("title"))
        href = clean_text(title_tag.get("href"))
        if not title or not href:
            continue

        cells = node.find_all("td", recursive=False)
        date_node = node.select_one(".article-date, .date, .publish-time")
        summary_node = node.select_one(".article-brief, .summary, .desc")
        if cells:
            summary = clean_text(cells[2].get_text(" ") if len(cells) > 2 else "")
            date_text = clean_text(cells[3].get_text(" ") if len(cells) > 3 else "")
        else:
            date_text = clean_text(date_node.get_text(" ") if date_node else "")
            summary = clean_text(summary_node.get_text(" ") if summary_node else "")

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


def extract_draft_date_summary(text: str) -> tuple[Optional[str], str]:
    match = DRAFT_DATES_PATTERN.search(clean_text(text))
    if not match:
        return None, ""

    start_date = match.group("start")
    return format_datetime(start_date), clean_text(match.group(0))


def find_draft_item_text(anchor) -> str:
    fallback_text = ""

    for parent in anchor.parents:
        if not getattr(parent, "find_all", None):
            continue

        text = clean_text(parent.get_text(" "))
        if "Ngày bắt đầu" not in text:
            continue

        if not fallback_text:
            fallback_text = text

        anchors = parent.find_all("a")
        if len(anchors) <= 3 or parent.name in {"article", "li", "tr"}:
            return text

    return fallback_text


def extract_draft_listing_articles(html: str) -> list[ParsedArticle]:
    soup = BeautifulSoup(html, "html.parser")
    articles: list[ParsedArticle] = []

    for title_tag in soup.find_all("a", href=True):
        href = clean_text(title_tag.get("href"))
        title = clean_text(title_tag.get_text(" ") or title_tag.get("title"))

        if not href or "/du-thao-van-ban/" not in href:
            continue
        if not title or title.lower() == "xem góp ý":
            continue

        item_text = find_draft_item_text(title_tag)
        published_at, summary = extract_draft_date_summary(item_text)

        articles.append(
            ParsedArticle(
                title=title,
                url=urljoin(BASE_SITE_URL, href.lstrip("/")),
                source=SOURCE_NAME,
                published_at=published_at,
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
    listing_sources = [
        build_news_listing_source(category_id, parent_id),
        LEGAL_DOCUMENT_LISTING_SOURCE,
    ]

    for listing_source in listing_sources:
        for page_no in range(1, max_pages + 1):
            try:
                logging.info(
                    "Fetching MOIT source=%s page_no=%s items_per_page=%s",
                    listing_source.article_type,
                    page_no,
                    items_per_page,
                )
                html = fetch_listing_page(
                    session=session,
                    page_no=page_no,
                    items_per_page=items_per_page,
                    listing_source=listing_source,
                )
                listing_articles = extract_listing_articles(html)

                if not listing_articles:
                    logging.info("No articles found on source=%s page_no=%s", listing_source.article_type, page_no)
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

                if len(results) >= max_articles:
                    break

                time.sleep(POLITE_DELAY_SECONDS)

                if len(listing_articles) < items_per_page:
                    break

            except Exception as exc:
                logging.warning("Failed source=%s page_no=%s: %s", listing_source.article_type, page_no, exc)
                break

    for page_no in range(1, max_pages + 1):
        try:
            listing_url = build_draft_listing_page_url(page_no)
            logging.info("Fetching MOIT draft listing page_no=%s url=%s", page_no, listing_url)
            html = fetch_html(session, listing_url)
            listing_articles = extract_draft_listing_articles(html)

            if not listing_articles:
                logging.info("No draft articles found on page_no=%s", page_no)
                break

            should_stop = False

            for listing_article in listing_articles:
                if len(results) >= max_articles:
                    break

                if is_older_than_window(listing_article.published_at, days):
                    logging.info("Stop at old draft article date: %s", listing_article.title)
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
                        logging.warning("Failed to fetch draft detail %s: %s", listing_article.url, exc)

                if not article.title:
                    logging.info("Skip draft article without title: %s", listing_article.url)
                    continue

                if not is_within_days(article.published_at, days):
                    logging.info("Skip old draft article: %s", article.title)
                    continue

                if filter_relevant and not is_relevant_article(
                    article,
                    require_legal_keyword=require_legal_keyword,
                    require_topic_keyword=require_topic_keyword,
                ):
                    logging.info("Skip irrelevant draft article: %s", article.title)
                    continue

                results.append(article_to_json_dict(article))

            if should_stop:
                break

            if len(results) >= max_articles:
                break

            time.sleep(POLITE_DELAY_SECONDS)

            if len(listing_articles) < items_per_page:
                break

        except Exception as exc:
            logging.warning("Failed draft page_no=%s: %s", page_no, exc)
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
        filter_relevant=True,
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
