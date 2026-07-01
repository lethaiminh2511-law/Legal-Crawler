from __future__ import annotations

import argparse
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from crawlers.common.keywords import LEGAL_KEYWORDS, TOPIC_KEYWORDS

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

SOURCE_NAME = "Dự thảo Online Quốc hội"
BASE_SITE_URL = "https://duthaoonline.quochoi.vn/"

REQUEST_TIMEOUT = 25
POLITE_DELAY_SECONDS = 0.7

DATE_PATTERN = re.compile(r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b")
D1N_COOKIE_PATTERN = re.compile(r'document\.cookie="D1N=([^"]+)')
TOTAL_PATTERN = re.compile(r"\+\s*(\d+)\s*\+\s*\"\)\"")

HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-language": "vi,en-US;q=0.9,en;q=0.8",
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/148.0.0.0 Safari/537.36"
    ),
}

AJAX_HEADERS = {
    "accept": "text/html,*/*;q=0.8",
    "x-requested-with": "XMLHttpRequest",
}


@dataclass(frozen=True)
class SourceConfig:
    key: str
    page_url: str
    handler: str
    page_size: int
    document_type: str
    type_id: Optional[int] = None


@dataclass
class ParsedArticle:
    title: str
    url: str
    source: str
    published_at: Optional[str]
    summary_raw: str
    category: str
    status: str
    document_type: str
    draft_round: str = ""
    expected_approval: str = ""


DEFAULT_SOURCES = [
    SourceConfig(
        key="du-thao-luat",
        page_url="https://duthaoonline.quochoi.vn/du-thao/du-thao-luat",
        handler="DanhSachDuThao",
        page_size=10,
        type_id=1,
        document_type="Dự thảo luật",
    ),
    SourceConfig(
        key="du-thao-phap-lenh",
        page_url="https://duthaoonline.quochoi.vn/du-thao/du-thao-phap-lenh",
        handler="DanhSachDuThao",
        page_size=10,
        type_id=2,
        document_type="Dự thảo pháp lệnh",
    ),
    SourceConfig(
        key="xay-dung-chinh-sach",
        page_url="https://duthaoonline.quochoi.vn/xay-dung-chinh-sach",
        handler="DanhSachDeXuatChinhSach",
        page_size=4,
        document_type="Xây dựng chính sách",
    ),
    SourceConfig(
        key="du-thao-nghi-quyet",
        page_url="https://duthaoonline.quochoi.vn/du-thao/du-thao-nghi-quyet",
        handler="DanhSachDuThao",
        page_size=10,
        type_id=3,
        document_type="Dự thảo nghị quyết",
    ),
]

STATUS_LABELS = {
    "DanhSachDuThao": {
        0: "Đang lấy ý kiến",
        1: "Đã thông qua",
    },
    "DanhSachDeXuatChinhSach": {
        0: "Đang lấy ý kiến",
        1: "Đã hết hạn lấy ý kiến",
    },
}


def clean_text(text: Optional[str]) -> str:
    if not text:
        return ""
    text = text.replace("\ufeff", "").replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_for_search(text: str) -> str:
    return clean_text(text).lower()


def fetch_html(session: requests.Session, url: str, **kwargs: object) -> str:
    response = session.get(url, timeout=REQUEST_TIMEOUT, **kwargs)
    response.raise_for_status()

    if not response.encoding or response.encoding.lower() in {"iso-8859-1", "gbk"}:
        response.encoding = response.apparent_encoding

    return response.text


def bootstrap_d1n_cookie(session: requests.Session, url: str) -> None:
    html = fetch_html(session, url)
    match = D1N_COOKIE_PATTERN.search(html)
    if match:
        session.cookies.set("D1N", match.group(1), domain="duthaoonline.quochoi.vn", path="/")


def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    bootstrap_d1n_cookie(session, BASE_SITE_URL)
    return session


def try_parse_datetime(raw: Optional[str]) -> Optional[datetime]:
    raw_text = clean_text(raw)
    if not raw_text:
        return None

    match = DATE_PATTERN.search(raw_text)
    if match:
        day, month, year = match.groups()
        raw_text = f"{day.zfill(2)}/{month.zfill(2)}/{year}"

    candidates = [
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
    ]

    for fmt in candidates:
        try:
            parsed = datetime.strptime(raw_text, fmt)
            return parsed.replace(tzinfo=VN_TZ).astimezone(VN_TZ)
        except ValueError:
            continue

    return None


def format_datetime(raw: Optional[str]) -> Optional[str]:
    parsed = try_parse_datetime(raw)
    if not parsed:
        return None
    return parsed.strftime("%Y-%m-%d %H:%M")


def parse_date_arg(raw: str) -> Optional[date]:
    parsed = try_parse_datetime(raw)
    if parsed:
        return parsed.date()
    return None


def get_start_date(days: Optional[int], date_from: Optional[date]) -> Optional[date]:
    if date_from:
        return date_from
    if days is None:
        return None

    day_count = max(days, 1)
    return (datetime.now(VN_TZ) - timedelta(days=day_count - 1)).date()


def labeled_value(node: BeautifulSoup, label: str) -> str:
    for paragraph in node.find_all("p"):
        span = paragraph.find("span")
        if not span:
            continue

        span_text = clean_text(span.get_text(" "))
        if label.lower() not in span_text.lower():
            continue

        paragraph_text = clean_text(paragraph.get_text(" "))
        return clean_text(paragraph_text.replace(span_text, "", 1))

    return ""


def first_date_text(node: BeautifulSoup) -> str:
    match = DATE_PATTERN.search(clean_text(node.get_text(" ")))
    return match.group(0) if match else ""


def extract_draft_round(node: BeautifulSoup) -> str:
    for link in node.select("a"):
        text = clean_text(link.get_text(" "))
        if "lần dự thảo" in text.lower():
            return text
    return ""


def extract_listing_articles(
    html: str,
    source_config: SourceConfig,
    status_code: int,
) -> list[ParsedArticle]:
    soup = BeautifulSoup(html, "html.parser")
    articles: list[ParsedArticle] = []
    status = STATUS_LABELS.get(source_config.handler, {}).get(status_code, str(status_code))

    for node in soup.select(".blog_details"):
        title_tag = node.select_one("a.d-inline-block h2")
        link_tag = title_tag.find_parent("a") if title_tag else None
        if not title_tag or not link_tag:
            continue

        href = clean_text(link_tag.get("href"))
        title = clean_text(title_tag.get_text(" "))
        if not href or not title:
            continue

        source = labeled_value(node, "Cơ quan trình") or labeled_value(node, "Cơ quan đề xuất")
        expected_approval = labeled_value(node, "Dự kiến thông qua")
        purpose = labeled_value(node, "Mục đích")
        draft_round = extract_draft_round(node)

        summary_parts = [
            f"Cơ quan: {source}" if source else "",
            f"Dự kiến thông qua: {expected_approval}" if expected_approval else "",
            f"Mục đích: {purpose}" if purpose else "",
            draft_round,
        ]

        articles.append(
            ParsedArticle(
                title=title,
                url=urljoin(BASE_SITE_URL, href.lstrip("/")),
                source=source or SOURCE_NAME,
                published_at=format_datetime(first_date_text(node)),
                summary_raw=clean_text(" ".join(part for part in summary_parts if part)),
                category=source_config.key,
                status=status,
                document_type=source_config.document_type,
                draft_round=draft_round,
                expected_approval=expected_approval,
            )
        )

    return articles


def extract_total_count(html: str) -> Optional[int]:
    match = TOTAL_PATTERN.search(html)
    if match:
        return int(match.group(1))
    return None


def fetch_listing_page(
    session: requests.Session,
    source_config: SourceConfig,
    status_code: int,
    page: int,
) -> str:
    params: dict[str, object] = {
        "handler": source_config.handler,
        "pageNumber": page,
        "PageSize": source_config.page_size,
        "ContainerBindData": "nav-profile" if status_code == 0 else "nav-contact",
        "TrangThai": status_code,
    }
    if source_config.type_id is not None:
        params["Type"] = source_config.type_id

    headers = {**AJAX_HEADERS, "referer": source_config.page_url}
    return fetch_html(session, source_config.page_url, params=params, headers=headers)


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
    require_topic_keyword: bool = False,
) -> bool:
    searchable_text = " ".join(
        [
            article.title,
            article.summary_raw,
            article.document_type,
            article.status,
        ]
    )
    legal_hits = keyword_hits(searchable_text, LEGAL_KEYWORDS)
    topic_hits = keyword_hits(searchable_text, TOPIC_KEYWORDS)

    if require_legal_keyword and not legal_hits:
        return False

    if require_topic_keyword and not topic_hits:
        return False

    return True


def article_date(article: ParsedArticle) -> Optional[date]:
    parsed = try_parse_datetime(article.published_at)
    if not parsed:
        return None
    return parsed.date()


def is_within_date_window(
    article: ParsedArticle,
    start_date: Optional[date],
    end_date: Optional[date],
) -> bool:
    parsed_date = article_date(article)
    if not parsed_date:
        return True

    if start_date and parsed_date < start_date:
        return False

    if end_date and parsed_date > end_date:
        return False

    return True


def is_older_than_window(article: ParsedArticle, start_date: Optional[date]) -> bool:
    parsed_date = article_date(article)
    if not start_date or not parsed_date:
        return False

    return parsed_date < start_date


def article_to_json_dict(article: ParsedArticle) -> dict:
    return {
        "title": article.title,
        "url": article.url,
        "source": article.source,
        "published_at": article.published_at,
        "summary_raw": article.summary_raw,
        "category": article.category,
        "status": article.status,
        "document_type": article.document_type,
        "draft_round": article.draft_round,
        "expected_approval": article.expected_approval,
    }


def crawl_duthaoonline(
    days: Optional[int] = 1,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    max_articles: int = 50,
    max_pages_per_source: int = 5,
    filter_relevant: bool = True,
    require_legal_keyword: bool = True,
    require_topic_keyword: bool = False,
    source_keys: Optional[list[str]] = None,
) -> list[dict]:
    """
    Main function để đưa vào hệ thống.

    Returns:
        list[dict] theo format gần giống các crawler legal tracking khác:
        {
          "title": "...",
          "url": "...",
          "source": "Chính phủ",
          "published_at": "2026-06-22 00:00",
          "summary_raw": "...",
          "category": "du-thao-luat",
          "status": "Đang lấy ý kiến",
          "document_type": "Dự thảo luật",
          "draft_round": "Lần dự thảo 2",
          "expected_approval": "Khóa XVI - Kỳ họp thứ 2"
        }
    """
    logging.info("Start crawling DuthaoOnline")

    start_date = get_start_date(days, parse_date_arg(date_from or ""))
    end_date = parse_date_arg(date_to or "")
    enabled_keys = set(source_keys or [source.key for source in DEFAULT_SOURCES])
    source_configs = [source for source in DEFAULT_SOURCES if source.key in enabled_keys]

    session = create_session()

    results: list[dict] = []
    seen_links: set[str] = set()

    for source_config in source_configs:
        if len(results) >= max_articles:
            break

        bootstrap_d1n_cookie(session, source_config.page_url)
        logging.info("Start source=%s", source_config.key)

        for status_code in (0, 1):
            if len(results) >= max_articles:
                break

            total_count: Optional[int] = None

            for page in range(1, max_pages_per_source + 1):
                if len(results) >= max_articles:
                    break

                try:
                    logging.info(
                        "Fetching source=%s status=%s page=%s",
                        source_config.key,
                        status_code,
                        page,
                    )
                    html = fetch_listing_page(session, source_config, status_code, page)
                    listing_articles = extract_listing_articles(
                        html,
                        source_config=source_config,
                        status_code=status_code,
                    )

                    if total_count is None:
                        total_count = extract_total_count(html)

                    if not listing_articles:
                        logging.info(
                            "No articles found for source=%s status=%s page=%s",
                            source_config.key,
                            status_code,
                            page,
                        )
                        break

                    should_stop = False
                    for article in listing_articles:
                        if len(results) >= max_articles:
                            break

                        if is_older_than_window(article, start_date):
                            logging.info("Stop at old item: %s", article.title)
                            should_stop = True
                            break

                        if article.url in seen_links:
                            continue
                        seen_links.add(article.url)

                        if not is_within_date_window(article, start_date, end_date):
                            logging.info("Skip out-of-window item: %s", article.title)
                            continue

                        if filter_relevant and not is_relevant_article(
                            article,
                            require_legal_keyword=require_legal_keyword,
                            require_topic_keyword=require_topic_keyword,
                        ):
                            logging.info("Skip irrelevant item: %s", article.title)
                            continue

                        results.append(article_to_json_dict(article))

                    time.sleep(POLITE_DELAY_SECONDS)

                    if should_stop:
                        break
                    if total_count is not None and page * source_config.page_size >= total_count:
                        break
                    if len(listing_articles) < source_config.page_size:
                        break

                except Exception as exc:
                    logging.warning(
                        "Failed source=%s status=%s page=%s: %s",
                        source_config.key,
                        status_code,
                        page,
                        exc,
                    )
                    break

    logging.info("Finished. Parsed %d DuthaoOnline items.", len(results))
    return results


def parse_source_keys(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crawl DuthaoOnline Quốc hội draft/policy pages and export JSON."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=1,
        help="Chỉ lấy bài trong N ngày gần nhất. Mặc định: 1. Dùng --days 0 để bỏ lọc ngày.",
    )
    parser.add_argument(
        "--date-from",
        type=str,
        default="",
        help="Ngày bắt đầu, ví dụ 2026-06-01 hoặc 01/06/2026. Ưu tiên hơn --days.",
    )
    parser.add_argument(
        "--date-to",
        type=str,
        default="",
        help="Ngày kết thúc, ví dụ 2026-06-27 hoặc 27/06/2026.",
    )
    parser.add_argument(
        "--max-articles",
        type=int,
        default=50,
        help="Số bài tối đa trả về. Mặc định: 50.",
    )
    parser.add_argument(
        "--max-pages-per-source",
        type=int,
        default=5,
        help="Số page tối đa cho mỗi nguồn/trạng thái. Mặc định: 5.",
    )
    parser.add_argument(
        "--sources",
        type=str,
        default=",".join(source.key for source in DEFAULT_SOURCES),
        help=(
            "Nguồn cần crawl, ngăn cách bằng dấu phẩy. "
            "Mặc định: du-thao-luat,du-thao-phap-lenh,xay-dung-chinh-sach,du-thao-nghi-quyet."
        ),
    )
    parser.add_argument(
        "--no-filter",
        action="store_true",
        help="Không lọc keyword; lấy tất cả bản ghi trong khoảng ngày.",
    )
    parser.add_argument(
        "--require-topic-keyword",
        action="store_true",
        help="Yêu cầu trúng keyword chủ đề công nghệ/IP như các crawler khác.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="duthaoonline_articles.json",
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

    articles = crawl_duthaoonline(
        days=None if args.days == 0 else args.days,
        date_from=args.date_from,
        date_to=args.date_to,
        max_articles=args.max_articles,
        max_pages_per_source=args.max_pages_per_source,
        filter_relevant=not args.no_filter,
        require_legal_keyword=True,
        require_topic_keyword=args.require_topic_keyword,
        source_keys=parse_source_keys(args.sources),
    )

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)

    if args.pretty:
        print(json.dumps(articles, ensure_ascii=False, indent=2))

    print(f"Saved {len(articles)} articles to {args.output}")


if __name__ == "__main__":
    main()
