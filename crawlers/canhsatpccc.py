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

from crawlers.common.keywords import LEGAL_KEYWORDS, TOPIC_KEYWORDS

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

SOURCE_NAME = "Cục Cảnh sát PCCC và CNCH"
BASE_SITE_URL = "https://canhsatpccc.gov.vn"

DEFAULT_SEED_URLS = [
    "https://canhsatpccc.gov.vn/vi/news",
]

ARTICLE_URL_PATTERN = re.compile(r"/vi/news/.+-\d+/?$", re.IGNORECASE)
DATE_PATTERN = re.compile(
    r"\b(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}(?::\d{2})?)\s*(AM|PM)?\b",
    re.IGNORECASE,
)

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


def normalize_for_search(text: str) -> str:
    return clean_text(text).lower()


def fetch_html(session: requests.Session, url: str) -> str:
    response = session.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    if not response.encoding or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding

    return response.text


def is_canhsatpccc_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.netloc.endswith("canhsatpccc.gov.vn")


def is_article_url(url: str) -> bool:
    parsed = urlparse(url)
    if not is_canhsatpccc_url(url):
        return False
    return bool(ARTICLE_URL_PATTERN.search(parsed.path.rstrip("/")))


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
    news_title = soup.select_one(".news_title")
    if news_title:
        title = clean_text(news_title.get_text(" "))
        if title:
            return title

    h1 = soup.find("h1")
    if h1:
        title = clean_text(h1.get_text(" "))
        if title:
            return title

    h2 = soup.find("h2")
    if h2:
        title = clean_text(h2.get_text(" "))
        if title:
            return title

    og_title = extract_meta_content(soup, ("property", "og:title"))
    if og_title:
        return og_title.replace(" - Cục Cảnh sát PCCC và CNCH", "").strip()

    if soup.title:
        return clean_text(soup.title.get_text(" ")).replace(
            " - Cục Cảnh sát PCCC và CNCH", ""
        ).strip()

    return ""


def normalize_pccc_datetime_text(raw: str) -> str:
    raw = clean_text(raw)

    dashed_iso = re.fullmatch(
        r"(\d{4}-\d{2}-\d{2})T(\d{2})-(\d{2})-(\d{2})",
        raw,
    )
    if dashed_iso:
        return (
            f"{dashed_iso.group(1)} "
            f"{dashed_iso.group(2)}:{dashed_iso.group(3)}:{dashed_iso.group(4)}"
        )

    # The site emits Vietnamese 24-hour times with an AM/PM suffix, for example
    # "01/06/2026 16:06:17 PM". Keep the 24-hour time and ignore the suffix.
    match = DATE_PATTERN.search(raw)
    if match:
        return f"{match.group(1)} {match.group(2)}"

    return raw


def try_parse_datetime(raw: str) -> Optional[datetime]:
    raw = normalize_pccc_datetime_text(raw)

    candidates = [
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d/%m/%Y",
        "%Y-%m-%d",
    ]

    if raw.endswith("Z"):
        raw = raw[:-1] + "+0000"

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
        ("name", "DC.Date"),
        ("name", "Date.Created"),
        ("name", "Date.Modified"),
    )
    if meta_date:
        parsed = try_parse_datetime(meta_date)
        if parsed:
            return parsed.strftime("%Y-%m-%d %H:%M")

    time_tag = soup.find("time")
    if time_tag:
        time_text = clean_text(time_tag.get("datetime") or time_tag.get_text(" "))
        parsed = try_parse_datetime(time_text)
        if parsed:
            return parsed.strftime("%Y-%m-%d %H:%M")

    page_text = clean_text(soup.get_text(" "))
    match = DATE_PATTERN.search(page_text)
    if match:
        parsed = try_parse_datetime(match.group(0))
        if parsed:
            return parsed.strftime("%Y-%m-%d %H:%M")

    return None


def get_candidate_content_container(soup: BeautifulSoup) -> BeautifulSoup:
    selectors = [
        "article",
        ".detail-content",
        ".article-content",
        ".news-content",
        ".content-detail",
        ".content_detail",
        ".bodytext",
        ".details-content",
        ".entry-content",
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
        "latest",
        "newest",
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
    soup = BeautifulSoup(str(soup), "html.parser")
    remove_noise(soup)
    container = get_candidate_content_container(soup)
    paragraphs: list[str] = []

    for tag in container.find_all(["p", "div"], recursive=True):
        text = clean_text(tag.get_text(" "))

        if not text:
            continue

        lower = text.lower()
        if any(
            bad in lower
            for bad in [
                "bản quyền thuộc",
                "ghi rõ nguồn",
                "đường dây nóng",
                "điện thoại pccc",
                "tin tức mới nhất",
                "tin tức liên quan",
                "chia sẻ",
            ]
        ):
            continue

        if len(text) < 30:
            continue

        if text not in paragraphs:
            paragraphs.append(text)

    return paragraphs


def extract_summary(soup: BeautifulSoup) -> str:
    meta_description = extract_meta_content(
        soup,
        ("name", "description"),
        ("property", "og:description"),
    )
    if meta_description:
        return meta_description

    paragraphs = extract_paragraphs(soup)
    return paragraphs[0] if paragraphs else ""


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


def is_within_days(published_at: Optional[str], days: Optional[int]) -> bool:
    if days is None:
        return True

    if not published_at:
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


def crawl_canh_sat_pccc(
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
          "source": "Cục Cảnh sát PCCC và CNCH",
          "published_at": "2026-06-14 08:30",
          "summary_raw": "..."
        }
    """
    logging.info("Start crawling Canh Sat PCCC")

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


def parse_seed_urls(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crawl Canh Sat PCCC and export legal/PCCC updates as JSON."
    )
    parser.add_argument(
        "--seed-urls",
        type=str,
        default=",".join(DEFAULT_SEED_URLS),
        help="Danh sách seed URL, ngăn cách bằng dấu phẩy. Mặc định: trang /vi/news.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=1,
        help="Chỉ lấy bài trong N ngày gần nhất. Mặc định: 1. Dùng --days 0 để bỏ lọc ngày.",
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
        default="canhsatpccc_articles.json",
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

    articles = crawl_canh_sat_pccc(
        seed_urls=parse_seed_urls(args.seed_urls),
        days=None if args.days == 0 else args.days,
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
