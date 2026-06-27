from __future__ import annotations

import argparse
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup


VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

SOURCE_NAME = "Cổng Thông tin điện tử Bộ Khoa học và Công nghệ"
BASE_SITE_URL = "https://mst.gov.vn/"
DATE_PAGE_TEMPLATE = "https://mst.gov.vn/tin-tuc-su-kien/xem-theo-ngay-{date}.htm"

ARTICLE_URL_PATTERN = re.compile(
    r"/(?!tin-tuc-su-kien/xem-theo-ngay-)[^/?#]+-\d{6,}\.htm$",
    re.IGNORECASE,
)
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
FETCH_RETRIES = 2
POLITE_DELAY_SECONDS = 0.8


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
    "ban hành",
    "có hiệu lực",
    "sửa đổi",
    "bổ sung",
    "sửa đổi, bổ sung",
    "thay thế",
    "bãi bỏ",
    "hướng dẫn thi hành",
    "quy định chi tiết",
    "xử phạt",
    "vi phạm hành chính",
    "thủ tục hành chính",
    "điều kiện kinh doanh",
    "giấy phép",
    "cấp phép",
    "đăng ký",
    "thông báo",
    "báo cáo",
    "kiểm tra",
    "thanh tra",
    "hậu kiểm",
    "quy chuẩn",
    "tiêu chuẩn",
    "quy chế",
    "chính sách mới",
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
    "công nghệ cao",
    "công nghệ chiến lược",
    "công nghệ mới",
    "nền tảng số",
    "dịch vụ số",
    "phần mềm",
    "thương mại điện tử",
    "giao dịch điện tử",
    "hợp đồng điện tử",
    "chữ ký điện tử",
    "chữ ký số",
    "sở hữu trí tuệ",
    "quyền sở hữu trí tuệ",
    "quyền tác giả",
    "bản quyền",
    "nhãn hiệu",
    "sáng chế",
    "kiểu dáng công nghiệp",
    "bí mật kinh doanh",
    "chỉ dẫn địa lý",
    "giống cây trồng",
    "tiêu chuẩn đo lường chất lượng",
    "tiêu chuẩn",
    "quy chuẩn kỹ thuật",
    "đổi mới sáng tạo",
    "nghiên cứu khoa học",
]


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
    last_exc: Optional[Exception] = None

    for attempt in range(1, FETCH_RETRIES + 1):
        try:
            response = session.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()

            if not response.encoding or response.encoding.lower() == "iso-8859-1":
                response.encoding = response.apparent_encoding

            return response.text
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < FETCH_RETRIES:
                logging.warning(
                    "Fetch failed attempt %s/%s for %s: %s",
                    attempt,
                    FETCH_RETRIES,
                    url,
                    exc,
                )
                time.sleep(POLITE_DELAY_SECONDS)

    raise last_exc or RuntimeError(f"Failed to fetch {url}")


def normalize_target_date(raw_date: Optional[str]) -> str:
    if not raw_date:
        return datetime.now(VN_TZ).strftime("%d-%m-%Y")

    raw_date = clean_text(raw_date)
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw_date, fmt).strftime("%d-%m-%Y")
        except ValueError:
            continue

    raise ValueError("Date must be dd-mm-yyyy, dd/mm/yyyy, yyyy-mm-dd, or yyyy/mm/dd")


def build_date_page_url(target_date: str) -> str:
    return DATE_PAGE_TEMPLATE.format(date=normalize_target_date(target_date))


def is_bokhcn_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.netloc.endswith("mst.gov.vn")


def is_article_url(url: str) -> bool:
    parsed = urlparse(url)
    if not is_bokhcn_url(url):
        return False
    return bool(ARTICLE_URL_PATTERN.search(parsed.path))


def extract_article_links(html: str, page_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []

    for tag in soup.find_all("a", href=True):
        href = clean_text(tag.get("href"))
        absolute_url = urljoin(page_url, href).split("#")[0].split("?")[0].strip()

        if is_article_url(absolute_url):
            links.append(absolute_url)

    seen = set()
    unique_links = []
    for link in links:
        if link not in seen:
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
        ".detail__title",
    ]

    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            title = clean_text(node.get_text(" "))
            if title:
                return title

    og_title = extract_meta_content(soup, ("property", "og:title"), ("name", "title"))
    if og_title:
        return og_title.replace(" - Bộ Khoa học và Công nghệ", "").strip()

    if soup.title:
        return clean_text(soup.title.get_text(" ")).replace(
            " - Bộ Khoa học và Công nghệ", ""
        ).strip()

    return ""


def try_parse_datetime(raw: Optional[str]) -> Optional[datetime]:
    raw = clean_text(raw)
    if not raw:
        return None

    if raw.endswith("Z"):
        raw = raw[:-1] + "+0000"

    candidates = [
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y %H:%M",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d/%m/%Y",
        "%d-%m-%Y",
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


def extract_published_at(soup: BeautifulSoup) -> Optional[str]:
    meta_date = extract_meta_content(
        soup,
        ("property", "article:published_time"),
        ("name", "pubdate"),
        ("name", "publishdate"),
        ("name", "date"),
    )
    parsed = try_parse_datetime(meta_date)
    if parsed:
        return parsed.strftime("%Y-%m-%d %H:%M")

    time_tag = soup.find("time")
    if time_tag:
        parsed = try_parse_datetime(time_tag.get("datetime") or time_tag.get_text(" "))
        if parsed:
            return parsed.strftime("%Y-%m-%d %H:%M")

    for selector in [
        ".date",
        ".time",
        ".detail-time",
        ".article-date",
        ".news-date",
        ".publish-date",
        ".detail__time",
    ]:
        node = soup.select_one(selector)
        if node:
            parsed = try_parse_datetime(node.get_text(" "))
            if parsed:
                return parsed.strftime("%Y-%m-%d %H:%M")

    page_text = clean_text(soup.get_text(" "))
    match = DATE_PATTERN.search(page_text)
    if match:
        raw = f"{match.group(1)} {match.group(2) or '00:00'}"
        parsed = try_parse_datetime(raw)
        if parsed:
            return parsed.strftime("%Y-%m-%d %H:%M")

    return None


def extract_summary(soup: BeautifulSoup) -> str:
    meta_description = extract_meta_content(
        soup,
        ("name", "description"),
        ("property", "og:description"),
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


def parse_article(html: str, url: str) -> ParsedArticle:
    soup = BeautifulSoup(html, "html.parser")

    return ParsedArticle(
        title=extract_title(soup),
        url=url,
        source=SOURCE_NAME,
        published_at=extract_published_at(soup),
        summary_raw=extract_summary(soup),
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


def is_on_target_date(published_at: Optional[str], target_date: str) -> bool:
    if not published_at:
        # The listing page itself is date-scoped, so keep articles if detail parsing misses the date.
        return True

    parsed = try_parse_datetime(published_at)
    if not parsed:
        return True

    target = datetime.strptime(normalize_target_date(target_date), "%d-%m-%Y").date()
    return parsed.date() == target


def article_to_json_dict(article: ParsedArticle) -> dict[str, Optional[str]]:
    return {
        "title": article.title,
        "url": article.url,
        "source": article.source,
        "published_at": article.published_at,
        "summary_raw": article.summary_raw,
    }


def crawl_bo_khoa_hoc_cong_nghe(
    target_date: Optional[str] = None,
    max_articles: int = 50,
    filter_relevant: bool = False,
    require_legal_keyword: bool = True,
    require_topic_keyword: bool = True,
) -> list[dict[str, Optional[str]]]:
    """
    Crawl the MST date listing page.

    Change target_date, for example 26-06-2026, to get articles for that date only.
    """
    normalized_date = normalize_target_date(target_date)
    date_page_url = build_date_page_url(normalized_date)

    logging.info("Start crawling Bo Khoa hoc va Cong nghe date=%s", normalized_date)

    session = requests.Session()
    session.headers.update(HEADERS)

    results: list[dict[str, Optional[str]]] = []
    seen_urls: set[str] = set()

    try:
        html = fetch_html(session, date_page_url)
    except Exception as exc:
        logging.warning("Failed date page %s: %s", date_page_url, exc)
        logging.info("Finished. Parsed 0 articles.")
        return results

    article_urls = extract_article_links(html, date_page_url)
    logging.info("Found %d candidate article links", len(article_urls))

    for article_url in article_urls:
        if len(results) >= max_articles:
            break

        if article_url in seen_urls:
            continue
        seen_urls.add(article_url)

        try:
            logging.info("Fetching article: %s", article_url)
            article_html = fetch_html(session, article_url)
            article = parse_article(article_html, article_url)

            if not article.title:
                logging.info("Skip article without title: %s", article_url)
                continue

            if not is_on_target_date(article.published_at, normalized_date):
                logging.info("Skip article outside target date: %s", article.title)
                continue

            if filter_relevant and not is_relevant_article(
                article,
                require_legal_keyword=require_legal_keyword,
                require_topic_keyword=require_topic_keyword,
            ):
                logging.info("Skip irrelevant article: %s", article.title)
                continue

            results.append(article_to_json_dict(article))
            time.sleep(POLITE_DELAY_SECONDS)
        except Exception as exc:
            logging.warning("Failed article %s: %s", article_url, exc)

    logging.info("Finished. Parsed %d articles.", len(results))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crawl Bo Khoa hoc va Cong nghe date page and export articles as JSON."
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Ngày cần crawl, ví dụ 27-06-2026 hoặc 2026-06-27. Mặc định: hôm nay.",
    )
    parser.add_argument(
        "--max-articles",
        type=int,
        default=50,
        help="Số bài tối đa trả về. Mặc định: 50.",
    )
    parser.add_argument(
        "--filter-relevant",
        action="store_true",
        help="Lọc keyword pháp lý/chủ đề giống các crawler legal tracking khác.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="bokhcn_articles.json",
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

    articles = crawl_bo_khoa_hoc_cong_nghe(
        target_date=args.date,
        max_articles=args.max_articles,
        filter_relevant=args.filter_relevant,
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
