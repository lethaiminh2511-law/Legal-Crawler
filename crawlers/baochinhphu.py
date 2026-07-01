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
from crawlers.common.keywords import LEGAL_KEYWORDS, TOPIC_KEYWORDS, normalize_for_search


VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

SOURCE_NAME = "Báo Chính phủ"

# Các trang seed đã xác định là hữu ích cho legal/policy tracking
DEFAULT_SEED_URLS = [
    "https://baochinhphu.vn/"
]

# Chỉ lấy URL bài viết, tránh lấy URL chuyên mục.
# Ví dụ bài viết thường có dạng: ...-102260615165821089.htm
ARTICLE_URL_PATTERN = re.compile(r"-\d{9,}\.htm$", re.IGNORECASE)

DATE_PATTERN = re.compile(r"\b(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})\b")

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


def fetch_html(session: requests.Session, url: str) -> str:
    response = session.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    # requests thường tự đoán encoding, nhưng set rõ để tránh lỗi tiếng Việt
    if not response.encoding or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding

    return response.text


def is_baochinhphu_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.netloc.endswith("baochinhphu.vn")


def is_article_url(url: str) -> bool:
    parsed = urlparse(url)
    if not is_baochinhphu_url(url):
        return False
    return bool(ARTICLE_URL_PATTERN.search(parsed.path))


def extract_article_links(html: str, page_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []

    for tag in soup.find_all("a", href=True):
        href = clean_text(tag.get("href"))
        absolute_url = urljoin(page_url, href)

        # Bỏ fragment/query cho ổn định
        absolute_url = absolute_url.split("#")[0].strip()

        if is_article_url(absolute_url):
            links.append(absolute_url)

    # Deduplicate giữ nguyên thứ tự
    seen = set()
    unique_links = []
    for link in links:
        if link not in seen:
            seen.add(link)
            unique_links.append(link)

    return unique_links


def extract_meta_content(soup: BeautifulSoup, *selectors: tuple[str, str]) -> str:
    """
    selectors: tuple dạng (attribute_name, attribute_value)
    Ví dụ: ("property", "og:title"), ("name", "description")
    """
    for attr_name, attr_value in selectors:
        tag = soup.find("meta", attrs={attr_name: attr_value})
        if tag and tag.get("content"):
            return clean_text(tag.get("content"))
    return ""


def extract_title(soup: BeautifulSoup) -> str:
    h1 = soup.find("h1")
    if h1:
        title = clean_text(h1.get_text(" "))
        if title:
            return title

    og_title = extract_meta_content(soup, ("property", "og:title"))
    if og_title:
        return og_title.replace(" - Báo Chính phủ", "").strip()

    if soup.title:
        return clean_text(soup.title.get_text(" ")).replace(" - Báo Chính phủ", "").strip()

    return ""


def extract_published_at(soup: BeautifulSoup) -> Optional[str]:
    # 1. Thử lấy từ meta
    meta_date = extract_meta_content(
        soup,
        ("property", "article:published_time"),
        ("name", "pubdate"),
        ("name", "publishdate"),
    )
    if meta_date:
        parsed = try_parse_datetime(meta_date)
        if parsed:
            return parsed.strftime("%Y-%m-%d %H:%M")

    # 2. Thử lấy từ thẻ time
    time_tag = soup.find("time")
    if time_tag:
        time_text = clean_text(time_tag.get("datetime") or time_tag.get_text(" "))
        parsed = try_parse_datetime(time_text)
        if parsed:
            return parsed.strftime("%Y-%m-%d %H:%M")

    # 3. Fallback: regex trong text toàn trang, dạng 15/06/2026 16:36
    page_text = clean_text(soup.get_text(" "))
    match = DATE_PATTERN.search(page_text)
    if match:
        raw = f"{match.group(1)} {match.group(2)}"
        parsed = try_parse_datetime(raw)
        if parsed:
            return parsed.strftime("%Y-%m-%d %H:%M")

    return None


def try_parse_datetime(raw: str) -> Optional[datetime]:
    raw = clean_text(raw)

    candidates = [
        "%d/%m/%Y %H:%M",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
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


def get_candidate_content_container(soup: BeautifulSoup) -> BeautifulSoup:
    """
    Báo điện tử có thể đổi class HTML theo thời gian.
    Hàm này thử nhiều selector, nếu không có thì fallback về body.
    """
    selectors = [
        "article",
        ".detail-content",
        ".article-content",
        ".news-content",
        ".content-detail",
        ".content_detail",
        ".detail",
        ".main-content",
        ".main",
    ]

    for selector in selectors:
        node = soup.select_one(selector)
        if node and len(clean_text(node.get_text(" "))) > 300:
            return node

    return soup.body or soup


def remove_noise(soup: BeautifulSoup) -> None:
    for tag in soup(["script", "style", "noscript", "iframe", "svg"]):
        tag.decompose()

    noise_keywords = [
        "breadcrumb",
        "comment",
        "related",
        "social",
        "share",
        "advert",
        "banner",
        "footer",
        "header",
        "menu",
        "nav",
    ]

    for tag in soup.find_all(True):
        class_text = " ".join(tag.get("class", [])).lower()
        id_text = str(tag.get("id", "")).lower()
        combined = f"{class_text} {id_text}"

        if any(keyword in combined for keyword in noise_keywords):
            try:
                tag.decompose()
            except Exception:
                pass


def extract_paragraphs(soup: BeautifulSoup) -> list[str]:
    container = get_candidate_content_container(soup)
    paragraphs: list[str] = []

    for p in container.find_all(["p", "div"], recursive=True):
        text = clean_text(p.get_text(" "))

        if not text:
            continue

        # Bỏ các đoạn boilerplate thường gặp
        lower = text.lower()
        if any(
            bad in lower
            for bad in [
                "bản quyền thuộc",
                "ghi rõ nguồn",
                "tải ứng dụng",
                "quét mã qr",
                "theo dõi báo điện tử chính phủ",
                "đọc thêm",
                "tin liên quan",
                "chia sẻ",
            ]
        ):
            continue

        # Bỏ đoạn quá ngắn dễ là menu/label
        if len(text) < 30:
            continue

        # Tránh duplicate đoạn
        if text not in paragraphs:
            paragraphs.append(text)

    return paragraphs


def extract_summary(soup: BeautifulSoup) -> str:
    meta_description = extract_meta_content(
        soup,
        ("name", "description"),
        ("property", "og:description"),
    )
    return meta_description or ""


def parse_article(html: str, url: str) -> ParsedArticle:
    soup = BeautifulSoup(html, "html.parser")

    title = extract_title(soup)
    published_at = extract_published_at(soup)
    summary_raw = extract_summary(soup)

    return ParsedArticle(
        title=title,
        url=url,
        source=SOURCE_NAME,
        published_at=published_at,
        summary_raw=summary_raw,
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
    searchable_text = " ".join(
        [
            article.title,
            article.summary_raw,
        ]
    )

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
        # Không parse được ngày thì vẫn giữ lại để tránh miss bài quan trọng
        return True

    parsed = try_parse_datetime(published_at)
    if not parsed:
        return True

    cutoff = datetime.now(VN_TZ) - timedelta(days=days)
    return parsed >= cutoff


def article_to_json_dict(article: ParsedArticle) -> dict:
    return {
        "title": article.title,
        "url": article.url,
        "source": article.source,
        "published_at": article.published_at,
        "summary_raw": article.summary_raw,
    }


def crawl_bao_chinh_phu(
    seed_urls: Optional[list[str]] = None,
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
          "source": "Báo Chính phủ",
          "published_at": "2026-06-14 08:30",
          "summary_raw": "...",
          "content": "..."
        }
    """
    logging.info("Start crawling Bao Chinh Phu")

    seed_urls = seed_urls or DEFAULT_SEED_URLS
    session = requests.Session()

    all_links: list[str] = []

    for seed_url in seed_urls:
        try:
            logging.info("Fetching seed page: %s", seed_url)
            html = fetch_html(session, seed_url)
            links = extract_article_links(html, seed_url)
            logging.info("Found %d article links from %s", len(links), seed_url)
            all_links.extend(links)
            time.sleep(POLITE_DELAY_SECONDS)
        except Exception as exc:
            logging.warning("Failed to fetch seed page %s: %s", seed_url, exc)

    # Deduplicate links giữ nguyên thứ tự
    seen_links = set()
    unique_links = []
    for link in all_links:
        if link not in seen_links:
            seen_links.add(link)
            unique_links.append(link)

    results: list[dict] = []

    for url in unique_links:
        if len(results) >= max_articles:
            break

        try:
            logging.info("Fetching article: %s", url)
            html = fetch_html(session, url)
            article = parse_article(html, url)

            if not article.title:
                logging.info("Skip article without title: %s", url)
                continue

            if not is_within_days(article.published_at, days):
                logging.info("Skip old article: %s", url)
                continue

            if filter_relevant and not is_relevant_article(
                article,
                require_legal_keyword=require_legal_keyword,
                require_topic_keyword=require_topic_keyword,
            ):
                logging.info("Skip irrelevant article: %s", url)
                continue

            results.append(article_to_json_dict(article))
            time.sleep(POLITE_DELAY_SECONDS)

        except Exception as exc:
            logging.warning("Failed to parse article %s: %s", url, exc)

    logging.info("Finished. Parsed %d relevant articles.", len(results))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crawl Bao Chinh Phu and export legal/IP-tech updates as JSON."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=1,
        help="Chỉ lấy bài trong N ngày gần nhất. Mặc định: 1.",
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
        help="Không lọc keyword; lấy tất cả bài tìm được từ seed pages.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="baochinhphu_articles.json",
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

    articles = crawl_bao_chinh_phu(
        days=args.days,
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