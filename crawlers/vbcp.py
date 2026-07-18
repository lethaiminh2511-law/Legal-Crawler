from __future__ import annotations

import argparse
import html
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from crawlers.common.keywords import LEGAL_KEYWORDS, TOPIC_KEYWORDS, is_relevant_text

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

SOURCE_NAME = "Cổng Thông tin điện tử Chính phủ - Hệ thống văn bản"
BASE_SITE_URL = "https://vanban.chinhphu.vn/"
ALL_DOCUMENTS_URL = "https://vanban.chinhphu.vn/?mode=0&pageid=41852"

REQUEST_TIMEOUT = 25
POLITE_DELAY_SECONDS = 0.6
DEFAULT_PAGE_SIZE = 50

HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-language": "vi,en;q=0.9,en-US;q=0.8",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/148.0.0.0 Safari/537.36"
    ),
    "connection": "close",
}

POSTBACK_PATTERN = re.compile(
    r"__doPostBack\((?:'|&#39;)([^'&]+)(?:'|&#39;)\s*,\s*(?:'|&#39;)([^'&]*)(?:'|&#39;)\)"
)


@dataclass
class ParsedDocument:
    title: str
    url: str
    source: str
    published_at: Optional[str]
    summary_raw: str
    code: str = ""
    issued_date: str = ""
    effective_date: str = ""
    document_type: str = ""
    agency: str = ""
    signer: str = ""
    attachment_urls: list[str] = field(default_factory=list)


def clean_text(text: Optional[object]) -> str:
    if text is None:
        return ""
    text = str(text).replace("\xa0", " ")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def try_parse_datetime(raw: Optional[object]) -> Optional[datetime]:
    raw_text = clean_text(raw)
    if not raw_text:
        return None

    candidates = [
        "%d/%m/%Y %H:%M",
        "%d-%m-%Y %H:%M",
        "%d/%m/%Y",
        "%d-%m-%Y",
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


def get_cutoff_datetime(days: Optional[int]) -> Optional[datetime]:
    if days is None:
        return None
    return datetime.now(VN_TZ) - timedelta(days=days)


def get_oldest_document_datetime(documents: list[ParsedDocument]) -> Optional[datetime]:
    parsed_dates = [
        parsed
        for document in documents
        if (parsed := try_parse_datetime(document.published_at or document.issued_date))
    ]
    if not parsed_dates:
        return None
    return min(parsed_dates)


def fetch_html(session: requests.Session, url: str, **kwargs: object) -> str:
    response = session.request("GET", url, headers=HEADERS, timeout=REQUEST_TIMEOUT, **kwargs)
    response.raise_for_status()
    if not response.encoding or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding
    return response.text


def create_session() -> requests.Session:
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST"),
    )
    adapter = HTTPAdapter(max_retries=retry)

    session = requests.Session()
    session.headers.update(HEADERS)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def fetch_postback_page(
    session: requests.Session,
    url: str,
    current_html: str,
    event_argument: str,
) -> str:
    soup = BeautifulSoup(current_html, "html.parser")
    form = soup.find("form")
    if not form:
        raise ValueError("Cannot find ASP.NET form for pagination")

    fields: dict[str, str] = {}
    for input_tag in form.find_all("input"):
        name = input_tag.get("name")
        if not name:
            continue
        fields[name] = input_tag.get("value", "")

    event_target = find_grid_event_target(soup)
    if not event_target:
        raise ValueError("Cannot find ASP.NET GridView event target for pagination")

    fields["__EVENTTARGET"] = event_target
    fields["__EVENTARGUMENT"] = event_argument

    response = session.post(url, headers=HEADERS, data=fields, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    if not response.encoding or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding
    return response.text


def find_grid_event_target(soup: BeautifulSoup) -> str:
    for link in soup.select("tr.grid-pager a[href*='__doPostBack']"):
        href = link.get("href", "")
        match = POSTBACK_PATTERN.search(href)
        if match:
            return html.unescape(match.group(1))
    return ""


def parse_list_documents(page_html: str, page_url: str) -> list[ParsedDocument]:
    soup = BeautifulSoup(page_html, "html.parser")
    documents: list[ParsedDocument] = []

    for row in soup.select("tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) < 3:
            continue

        code_cell, issued_cell, summary_cell = cells[:3]
        code_node = code_cell.select_one(".code")
        summary_node = summary_cell.select_one(".substract")
        detail_link = summary_cell.select_one("a[href*='docid=']") or code_cell.select_one("a[href*='docid=']")

        if not code_node or not summary_node or not detail_link:
            continue

        code = clean_text(code_node.get_text(" "))
        summary = clean_text(summary_node.get_text(" "))
        issued_date_node = issued_cell.select_one(".issued-date")
        issued_date = clean_text(issued_date_node.get_text(" ") if issued_date_node else "")
        url = urljoin(page_url, detail_link.get("href", ""))
        attachment_urls = [
            urljoin(page_url, link.get("href", ""))
            for link in summary_cell.select(".bl-doc-files a[href]")
            if link.get("href")
        ]

        title = f"{code} - {summary}" if code and summary else code or summary
        summary_raw = build_summary(
            {
                "Số ký hiệu": code,
                "Ngày ban hành": issued_date,
                "Trích yếu": summary,
                "Tài liệu đính kèm": "\n".join(attachment_urls),
            }
        )

        documents.append(
            ParsedDocument(
                title=title,
                url=url,
                source=SOURCE_NAME,
                published_at=format_datetime(issued_date),
                summary_raw=summary_raw,
                code=code,
                issued_date=issued_date,
                attachment_urls=attachment_urls,
            )
        )

    return documents


def build_summary(fields: dict[str, str]) -> str:
    lines = []
    for label, value in fields.items():
        value = clean_text(value)
        if value:
            lines.append(f"{label}: {value}")
    return "\n".join(lines)


def extract_detail_fields(detail_html: str) -> dict[str, str]:
    soup = BeautifulSoup(detail_html, "html.parser")
    fields: dict[str, str] = {}

    title_node = soup.select_one("h4.title span, h4.title")
    if title_node:
        fields["title"] = clean_text(title_node.get_text(" "))

    content = soup.select_one(".Content")
    if content:
        for row in content.select("tr"):
            cells = row.find_all("td", recursive=False)
            if len(cells) < 2:
                continue
            label = clean_text(cells[0].get_text(" "))
            value = clean_text(cells[1].get_text(" "))
            if label and value:
                fields[label] = value

    file_urls = [
        urljoin(BASE_SITE_URL, link.get("href", ""))
        for link in soup.select(".rp-file a.view-file[href], .doc-list a[href]")
        if link.get("href") and not link.get("href", "").startswith("javascript:")
    ]
    if file_urls:
        fields["attachment_urls"] = "\n".join(dict.fromkeys(file_urls))

    return fields


def merge_detail_fields(document: ParsedDocument, fields: dict[str, str]) -> ParsedDocument:
    code = fields.get("Số ký hiệu", document.code)
    issued_date = fields.get("Ngày ban hành", document.issued_date)
    effective_date = fields.get("Ngày có hiệu lực", document.effective_date)
    document_type = fields.get("Loại văn bản", document.document_type)
    agency = fields.get("Cơ quan ban hành", document.agency)
    signer = fields.get("Người ký", document.signer)
    summary = fields.get("Trích yếu", "")
    title = fields.get("title") or (f"{code} - {summary}" if code and summary else document.title)
    attachment_urls = fields.get("attachment_urls", "")
    attachments = attachment_urls.splitlines() if attachment_urls else document.attachment_urls

    document.title = clean_text(title)
    document.published_at = format_datetime(issued_date) or document.published_at
    document.code = clean_text(code)
    document.issued_date = clean_text(issued_date)
    document.effective_date = clean_text(effective_date)
    document.document_type = clean_text(document_type)
    document.agency = clean_text(agency)
    document.signer = clean_text(signer)
    document.attachment_urls = [clean_text(item) for item in attachments if clean_text(item)]
    document.summary_raw = build_summary(
        {
            "Số ký hiệu": document.code,
            "Ngày ban hành": document.issued_date,
            "Ngày có hiệu lực": document.effective_date,
            "Loại văn bản": document.document_type,
            "Cơ quan ban hành": document.agency,
            "Người ký": document.signer,
            "Trích yếu": summary or document.summary_raw,
            "Tài liệu đính kèm": "\n".join(document.attachment_urls),
        }
    )
    return document


def document_to_json_dict(document: ParsedDocument) -> dict[str, object]:
    return {
        "title": document.title,
        "url": document.url,
        "source": document.source,
        "published_at": document.published_at,
        "summary_raw": document.summary_raw,
        "code": document.code,
        "issued_date": document.issued_date,
        "effective_date": document.effective_date,
        "document_type": document.document_type,
        "agency": document.agency,
        "signer": document.signer,
        "attachment_urls": document.attachment_urls,
    }


def is_relevant_document(
    document: ParsedDocument,
    require_legal_keyword: bool = True,
    require_topic_keyword: bool = True,
) -> bool:
    searchable_text = " ".join(
        [
            document.title,
            document.summary_raw,
            document.code,
            document.document_type,
            document.agency,
        ]
    )
    return is_relevant_text(
        searchable_text,
        legal_keywords=LEGAL_KEYWORDS,
        topic_keywords=TOPIC_KEYWORDS,
        require_legal_keyword=require_legal_keyword,
        require_topic_keyword=require_topic_keyword,
    )


def crawl_vbcp(
    days: Optional[int] = 1,
    max_articles: int = 50,
    max_pages: int = 1,
    fetch_details: bool = False,
    filter_relevant: bool = True,
    require_legal_keyword: bool = True,
    require_topic_keyword: bool = True,
) -> list[dict[str, object]]:
    """
    Crawl "Tất cả văn bản" from vanban.chinhphu.vn.

    Returns records with the same core keys as other crawlers plus document metadata:
    title, url, source, published_at, summary_raw, code, issued_date,
    effective_date, document_type, agency, signer, attachment_urls.
    """
    logging.info("Start crawling VBCP all documents")

    session = create_session()

    results: list[dict[str, object]] = []
    seen_urls: set[str] = set()
    cutoff = get_cutoff_datetime(days)

    current_html = fetch_html(session, ALL_DOCUMENTS_URL)

    for page_no in range(1, max_pages + 1):
        if len(results) >= max_articles:
            break

        if page_no > 1:
            logging.info("Fetching VBCP page=%s via ASP.NET postback", page_no)
            current_html = fetch_postback_page(
                session=session,
                url=ALL_DOCUMENTS_URL,
                current_html=current_html,
                event_argument=f"Page${page_no}",
            )

        documents = parse_list_documents(current_html, ALL_DOCUMENTS_URL)
        if not documents:
            logging.info("No documents found on page=%s", page_no)
            break

        logging.info("Found %d documents on page=%s", len(documents), page_no)
        oldest_page_date = get_oldest_document_datetime(documents)

        added_from_page = 0
        for document in documents:
            if len(results) >= max_articles:
                break

            if document.url in seen_urls:
                continue
            seen_urls.add(document.url)

            if not is_within_days(document.published_at, days):
                logging.info("Skip old document: %s", document.title)
                continue

            if fetch_details and document.url:
                try:
                    logging.info("Fetching VBCP detail: %s", document.url)
                    detail_html = fetch_html(session, document.url)
                    detail_fields = extract_detail_fields(detail_html)
                    document = merge_detail_fields(document, detail_fields)
                    time.sleep(POLITE_DELAY_SECONDS)
                except Exception as exc:
                    logging.warning("Failed to fetch detail %s: %s", document.url, exc)

            if filter_relevant and not is_relevant_document(
                document,
                require_legal_keyword=require_legal_keyword,
                require_topic_keyword=require_topic_keyword,
            ):
                logging.info("Skip non-relevant document: %s", document.title)
                continue

            results.append(document_to_json_dict(document))
            added_from_page += 1

        time.sleep(POLITE_DELAY_SECONDS)

        if cutoff and oldest_page_date and oldest_page_date < cutoff:
            logging.info(
                "Oldest document on page=%s is %s, before cutoff %s; stop pagination",
                page_no,
                oldest_page_date.strftime("%Y-%m-%d %H:%M"),
                cutoff.strftime("%Y-%m-%d %H:%M"),
            )
            break

        if added_from_page == 0:
            logging.info("No new documents added from page=%s; stop pagination", page_no)
            break

        if len(documents) < DEFAULT_PAGE_SIZE:
            break

    logging.info("Finished. Parsed %d VBCP documents.", len(results))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crawl vanban.chinhphu.vn 'Tất cả văn bản' and export JSON."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=1,
        help="Chỉ lấy văn bản trong N ngày gần nhất. Mặc định: 1. Dùng --days 0 để bỏ lọc ngày.",
    )
    parser.add_argument(
        "--max-articles",
        type=int,
        default=50,
        help="Số văn bản tối đa trả về. Mặc định: 50.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=1,
        help="Số trang danh sách tối đa, mỗi trang khoảng 50 văn bản. Mặc định: 1.",
    )
    parser.add_argument(
        "--fetch-details",
        action="store_true",
        help="Mở từng trang chi tiết để lấy thêm ngày hiệu lực, loại văn bản, cơ quan ban hành, người ký.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="vbcp_articles.json",
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

    articles = crawl_vbcp(
        days=None if args.days == 0 else args.days,
        max_articles=args.max_articles,
        max_pages=args.max_pages,
        fetch_details=args.fetch_details,
        filter_relevant=True,
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
