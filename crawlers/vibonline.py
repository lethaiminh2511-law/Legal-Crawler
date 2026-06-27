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
import urllib3
from bs4 import BeautifulSoup


VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

SOURCE_NAME = "VIB Online"
BASE_SITE_URL = "https://vibonline.com.vn/"
LISTING_URL_TEMPLATE = "https://vibonline.com.vn/du-thao/page/{page}"

DATE_PATTERN = re.compile(
    r"\b(?:(\d{1,2}:\d{2})(?:\:\d{2})?\s+)?(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b"
)

HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-language": "en,vi;q=0.9,en-US;q=0.8",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/148.0.0.0 Safari/537.36"
    ),
}

REQUEST_TIMEOUT = 25
POLITE_DELAY_SECONDS = 0.8

# The site currently serves a certificate chain that may fail local verification.
DEFAULT_VERIFY_SSL = False


LEGAL_KEYWORDS = [
    "dự thảo",
    "lấy ý kiến",
    "góp ý dự thảo",
    "nghị định",
    "thông tư",
    "quyết định",
    "nghị quyết",
    "chỉ thị",
    "luật",
    "pháp lệnh",
    "sửa đổi",
    "bổ sung",
    "quy định chi tiết",
    "thủ tục hành chính",
    "điều kiện kinh doanh",
    "giấy phép",
    "quy chuẩn",
    "tiêu chuẩn",
]

TOPIC_KEYWORDS = [
    "dữ liệu",
    "dữ liệu cá nhân",
    "an toàn thông tin",
    "an ninh mạng",
    "trí tuệ nhân tạo",
    "chuyển đổi số",
    "kinh tế số",
    "công nghệ số",
    "nền tảng số",
    "dịch vụ số",
    "mạng xã hội",
    "phần mềm",
    "thương mại điện tử",
    "giao dịch điện tử",
    "hợp đồng điện tử",
    "chữ ký điện tử",
    "thanh toán điện tử",
    "quảng cáo trực tuyến",
    "sở hữu trí tuệ",
    "quyền tác giả",
    "bản quyền",
    "nhãn hiệu",
    "sáng chế",
    "hàng giả",
]


@dataclass
class ParsedArticle:
    title: str
    url: str
    source: str
    published_at: Optional[str]
    summary_raw: str
    status: str = ""
    document_type: str = ""
    attachment_count: Optional[int] = None


def clean_text(text: Optional[str]) -> str:
    if not text:
        return ""
    text = text.replace("\ufeff", "").replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_for_search(text: str) -> str:
    return clean_text(text).lower()


def fetch_html(session: requests.Session, url: str, verify_ssl: bool) -> str:
    response = session.get(url, timeout=REQUEST_TIMEOUT, verify=verify_ssl)
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
        time_part, day, month, year = match.groups()
        raw_text = f"{day.zfill(2)}/{month.zfill(2)}/{year}"
        if time_part:
            raw_text = f"{raw_text} {time_part}"

    if raw_text.endswith("Z"):
        raw_text = raw_text[:-1] + "+0000"

    candidates = [
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
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
            parsed = datetime.strptime(raw_text, fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=VN_TZ)
            return parsed.astimezone(VN_TZ)
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


def extract_meta_content(soup: BeautifulSoup, *selectors: tuple[str, str]) -> str:
    for attr_name, attr_value in selectors:
        tag = soup.find("meta", attrs={attr_name: attr_value})
        if tag and tag.get("content"):
            return clean_text(tag.get("content"))
    return ""


def extract_listing_articles(html: str) -> list[ParsedArticle]:
    soup = BeautifulSoup(html, "html.parser")
    articles: list[ParsedArticle] = []

    for node in soup.select("article.draf-item"):
        title_tag = node.select_one(".information h3 a")
        if not title_tag:
            continue

        title = clean_text(title_tag.get_text(" ") or title_tag.get("title"))
        href = clean_text(title_tag.get("href"))
        if not title or not href:
            continue

        summary = clean_text(node.select_one(".information p").get_text(" ") if node.select_one(".information p") else "")
        date_text = clean_text(node.select_one(".draf-tool .date").get_text(" ") if node.select_one(".draf-tool .date") else "")
        agency = clean_text(node.select_one(".draf-tool .draf-term").get_text(" ") if node.select_one(".draf-tool .draf-term") else "")

        attachment_count = None
        download_text = clean_text(node.select_one(".draf-tool .download").get_text(" ") if node.select_one(".draf-tool .download") else "")
        count_match = re.search(r"\d+", download_text)
        if count_match:
            attachment_count = int(count_match.group(0))

        articles.append(
            ParsedArticle(
                title=title,
                url=urljoin(BASE_SITE_URL, href),
                source=agency,
                published_at=format_datetime(date_text),
                summary_raw=summary,
                attachment_count=attachment_count,
            )
        )

    return articles


def extract_title(soup: BeautifulSoup) -> str:
    h1 = soup.select_one(".draf-content-center h1") or soup.find("h1")
    if h1:
        title = clean_text(h1.get_text(" "))
        if title:
            return title

    og_title = extract_meta_content(soup, ("property", "og:title"), ("name", "title"))
    return re.sub(r"\s+-\s+VIB Online$", "", og_title).strip()


def extract_published_at(soup: BeautifulSoup) -> Optional[str]:
    detail_tool = soup.select_one(".draf-detail-tool p")
    if detail_tool:
        parsed = format_datetime(detail_tool.get_text(" "))
        if parsed:
            return parsed

    page_text = clean_text(soup.get_text(" "))
    match = DATE_PATTERN.search(page_text)
    if match:
        return format_datetime(match.group(0))

    return None


def extract_labeled_value(soup: BeautifulSoup, label: str) -> str:
    for heading in soup.select(".dot-title"):
        if label.lower() not in clean_text(heading.get_text(" ")).lower():
            continue

        sibling = heading.find_next_sibling("p")
        if sibling:
            return clean_text(sibling.get_text(" "))

        parent = heading.parent
        if parent:
            text = clean_text(parent.get_text(" "))
            return clean_text(text.replace(clean_text(heading.get_text(" ")), "", 1))

    return ""


def extract_bold_labeled_value(soup: BeautifulSoup, label: str) -> str:
    for bold in soup.find_all("b"):
        if label.lower() not in clean_text(bold.get_text(" ")).lower():
            continue

        parent = bold.parent
        if not parent:
            continue

        text = clean_text(parent.get_text(" "))
        return clean_text(text.replace(clean_text(bold.get_text(" ")), "", 1))

    return ""


def extract_summary(soup: BeautifulSoup) -> str:
    description = extract_meta_content(
        soup,
        ("name", "description"),
        ("property", "og:description"),
    )
    if description:
        return description

    for heading in soup.select(".dot-title"):
        if "tóm lược" not in clean_text(heading.get_text(" ")).lower():
            continue

        sibling = heading.find_next_sibling("p")
        if sibling:
            return clean_text(sibling.get_text(" "))

        parent = heading.parent
        if parent:
            text = clean_text(parent.get_text(" "))
            return clean_text(text.replace(clean_text(heading.get_text(" ")), "", 1))

    return ""


def parse_article_detail(html: str, fallback: ParsedArticle) -> ParsedArticle:
    soup = BeautifulSoup(html, "html.parser")
    agency = extract_labeled_value(soup, "Cơ quan chịu trách nhiệm soạn thảo")
    if not agency:
        agency = extract_labeled_value(soup, "Cơ quan soạn thảo")

    attachment_count = fallback.attachment_count
    file_items = soup.select(".file-item")
    if file_items:
        attachment_count = len(file_items)

    return ParsedArticle(
        title=extract_title(soup) or fallback.title,
        url=fallback.url,
        source=agency or fallback.source,
        published_at=extract_published_at(soup) or fallback.published_at,
        summary_raw=extract_summary(soup) or fallback.summary_raw,
        status=extract_labeled_value(soup, "Trạng thái") or fallback.status,
        document_type=(
            extract_labeled_value(soup, "Loại tài liệu")
            or extract_bold_labeled_value(soup, "Loại tài liệu")
            or fallback.document_type
        ),
        attachment_count=attachment_count,
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
    require_topic_keyword: bool = False,
) -> bool:
    searchable_text = " ".join([article.title, article.summary_raw, article.document_type])
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
        "published_at": article.published_at,
        "summary_raw": article.summary_raw,
        "source": article.source,
        "status": article.status,
        "document_type": article.document_type,
        "attachment_count": article.attachment_count,
    }


def crawl_vibonline(
    days: Optional[int] = 1,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    max_articles: int = 50,
    max_pages: int = 10,
    filter_relevant: bool = True,
    require_legal_keyword: bool = True,
    require_topic_keyword: bool = False,
    fetch_details: bool = True,
    verify_ssl: bool = DEFAULT_VERIFY_SSL,
) -> list[dict]:
    """
    Main function để đưa vào hệ thống.

    Returns:
        list[dict] theo format:
        {
          "title": "...",
          "url": "...",
          "source": "VIB Online",
          "published_at": "2026-06-19 16:52",
          "summary_raw": "...",
          "source": "Bộ Công an",
          "status": "Đang lấy ý kiến",
          "document_type": "Luật",
          "attachment_count": 9
        }
    """
    logging.info("Start crawling VibOnline draft listing")

    start_date = get_start_date(days, parse_date_arg(date_from or ""))
    end_date = parse_date_arg(date_to or "")

    if not verify_ssl:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    session = requests.Session()
    session.headers.update(HEADERS)

    results: list[dict] = []
    seen_links: set[str] = set()

    for page in range(1, max_pages + 1):
        if len(results) >= max_articles:
            break

        try:
            url = LISTING_URL_TEMPLATE.format(page=page)
            logging.info("Fetching VibOnline page=%s", page)
            html = fetch_html(session, url, verify_ssl=verify_ssl)
            listing_articles = extract_listing_articles(html)

            if not listing_articles:
                logging.info("No articles found on page=%s", page)
                break

            should_stop = False

            for listing_article in listing_articles:
                if len(results) >= max_articles:
                    break

                if is_older_than_window(listing_article, start_date):
                    logging.info("Stop at old draft date: %s", listing_article.title)
                    should_stop = True
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

                if not is_within_date_window(article, start_date, end_date):
                    logging.info("Skip out-of-window draft: %s", article.title)
                    continue

                if filter_relevant and not is_relevant_article(
                    article,
                    require_legal_keyword=require_legal_keyword,
                    require_topic_keyword=require_topic_keyword,
                ):
                    logging.info("Skip irrelevant draft: %s", article.title)
                    continue

                results.append(article_to_json_dict(article))

            time.sleep(POLITE_DELAY_SECONDS)

            if should_stop:
                break

        except Exception as exc:
            logging.warning("Failed page=%s: %s", page, exc)
            break

    logging.info("Finished. Parsed %d drafts.", len(results))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crawl VibOnline draft documents and export legal/IP-tech updates as JSON."
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
        "--max-pages",
        type=int,
        default=10,
        help="Số page tối đa cần crawl. Mặc định: 10.",
    )
    parser.add_argument(
        "--no-filter",
        action="store_true",
        help="Không lọc keyword; lấy tất cả dự thảo trong khoảng ngày.",
    )
    parser.add_argument(
        "--require-topic-keyword",
        action="store_true",
        help="Yêu cầu trúng keyword chủ đề công nghệ/IP như các crawler khác.",
    )
    parser.add_argument(
        "--no-details",
        action="store_true",
        help="Không fetch trang chi tiết; chỉ dùng dữ liệu ở listing.",
    )
    parser.add_argument(
        "--verify-ssl",
        action="store_true",
        help="Bật xác thực SSL. Mặc định tắt vì certificate chain của site có thể lỗi.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="vibonline_articles.json",
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

    articles = crawl_vibonline(
        days=None if args.days == 0 else args.days,
        date_from=args.date_from,
        date_to=args.date_to,
        max_articles=args.max_articles,
        max_pages=args.max_pages,
        filter_relevant=not args.no_filter,
        require_legal_keyword=True,
        require_topic_keyword=args.require_topic_keyword,
        fetch_details=not args.no_details,
        verify_ssl=args.verify_ssl,
    )

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)

    if args.pretty:
        print(json.dumps(articles, ensure_ascii=False, indent=2))

    print(f"Saved {len(articles)} articles to {args.output}")


if __name__ == "__main__":
    main()
