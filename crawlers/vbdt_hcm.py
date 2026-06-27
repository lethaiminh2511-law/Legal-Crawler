from __future__ import annotations

import argparse
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

import requests


VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

BASE_SITE_URL = "https://hochiminhcity.gov.vn"
API_LIST_URL = "https://hochiminhcity.gov.vn/van-ban-du-thao"
DETAIL_URL_TEMPLATE = (
    "https://hochiminhcity.gov.vn/van-ban-du-thao"
    "?p_p_id=VanBanDuThao_WAR_sdtvanbanportlet"
    "&p_p_lifecycle=0"
    "&p_p_state=normal"
    "&p_p_mode=view"
    "&_VanBanDuThao_WAR_sdtvanbanportlet_action=themMoi"
    "&id={id}"
    "&view=details"
)

REQUEST_TIMEOUT = 25
POLITE_DELAY_SECONDS = 0.6
DEFAULT_LIMIT = 50

HEADERS = {
    "accept": "application/json, text/javascript, */*; q=0.01",
    "accept-language": "en,vi;q=0.9,en-US;q=0.8",
    "referer": "https://hochiminhcity.gov.vn/van-ban-du-thao",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/148.0.0.0 Safari/537.36"
    ),
    "x-requested-with": "XMLHttpRequest",
}


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
    "nền tảng số",
    "dịch vụ số",
    "phần mềm",
    "thương mại điện tử",
    "giao dịch điện tử",
    "hợp đồng điện tử",
    "chữ ký điện tử",
    "chữ ký số",
    "thanh toán điện tử",
    "sở hữu trí tuệ",
    "quyền tác giả",
    "bản quyền",
    "nhãn hiệu",
    "sáng chế",
    "hàng giả",
    "hàng hóa giả mạo",
    "đô thị thông minh",
    "dịch vụ công trực tuyến",
    "cải cách hành chính",
]


@dataclass
class ParsedArticle:
    title: str
    url: str
    source: str
    published_at: Optional[str]
    summary_raw: str


def clean_text(text: Optional[Any]) -> str:
    if text is None:
        return ""
    text = str(text).replace("\xa0", " ")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_for_search(text: str) -> str:
    return clean_text(text).lower()


def first_present(record: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return None


def get_nested_text(record: dict[str, Any], key: str, nested_key: str) -> str:
    value = record.get(key)
    if isinstance(value, dict):
        return clean_text(value.get(nested_key))
    return clean_text(value)


def try_parse_datetime(raw: Optional[Any]) -> Optional[datetime]:
    raw_text = clean_text(raw)
    if not raw_text:
        return None

    if re.fullmatch(r"\d{10,13}", raw_text):
        timestamp = int(raw_text)
        if len(raw_text) == 13:
            timestamp = timestamp / 1000
        return datetime.fromtimestamp(timestamp, tz=VN_TZ)

    if raw_text.endswith("Z"):
        raw_text = raw_text[:-1] + "+0000"

    raw_text = re.sub(r"\bICT\b", "+0700", raw_text)

    candidates = [
        "%a %b %d %H:%M:%S %z %Y",
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


def format_datetime(raw: Optional[Any]) -> Optional[str]:
    parsed = try_parse_datetime(raw)
    if not parsed:
        return None
    return parsed.strftime("%Y-%m-%d %H:%M")


def format_summary_date(raw: Optional[Any]) -> str:
    return format_datetime(raw) or clean_text(raw)


def normalize_api_date(raw_date: Optional[str]) -> str:
    if not raw_date:
        return ""

    raw_date = clean_text(raw_date)
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw_date, fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue

    raise ValueError("Date must be dd/mm/yyyy, dd-mm-yyyy, yyyy-mm-dd, or yyyy/mm/dd")


def parse_api_date(raw_date: str) -> Optional[datetime.date]:
    if not raw_date:
        return None
    return datetime.strptime(raw_date, "%d/%m/%Y").date()


def get_date_range(days: Optional[int]) -> tuple[str, str]:
    if days is None:
        return "", ""

    day_count = max(days, 1)
    end_date = datetime.now(VN_TZ).date()
    start_date = end_date - timedelta(days=day_count - 1)
    return start_date.strftime("%d/%m/%Y"), end_date.strftime("%d/%m/%Y")


def extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if not isinstance(payload, dict):
        return []

    direct_list_keys = ["data", "items", "rows", "results", "list", "content", "vanBanDuThaos"]
    for key in direct_list_keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    nested_dict_keys = ["data", "result", "payload", "page"]
    for key in nested_dict_keys:
        value = payload.get(key)
        if isinstance(value, dict):
            items = extract_items(value)
            if items:
                return items

    return []


def build_detail_url(record: dict[str, Any]) -> str:
    document_id = first_present(record, ["id", "vanBanDuThaoId", "van_ban_du_thao_id"])
    if document_id in (None, ""):
        return ""
    return DETAIL_URL_TEMPLATE.format(id=clean_text(document_id))


def build_title(record: dict[str, Any]) -> str:
    so_ky_hieu = clean_text(record.get("soKyHieu"))
    trich_yeu = clean_text(record.get("trichYeu"))

    if so_ky_hieu and trich_yeu:
        return f"{so_ky_hieu} - {trich_yeu}"
    return so_ky_hieu or trich_yeu


def build_summary(record: dict[str, Any]) -> str:
    trich_yeu = clean_text(record.get("trichYeu"))
    ngay_lay_y_kien = format_summary_date(record.get("ngayLayYKien"))
    ngay_het_han = format_summary_date(record.get("ngayHetHan"))

    date_lines = []
    if ngay_lay_y_kien:
        date_lines.append(f"Ngày lấy ý kiến: {ngay_lay_y_kien}")
    if ngay_het_han:
        date_lines.append(f"Ngày hết hiệu lực: {ngay_het_han}")

    return "\n".join(part for part in [trich_yeu, *date_lines] if part)


def parse_article_record(record: dict[str, Any]) -> ParsedArticle:
    return ParsedArticle(
        title=build_title(record),
        url=build_detail_url(record),
        source=get_nested_text(record, "coQuanBanHanh", "ten") or "Cổng thông tin điện tử TP. Hồ Chí Minh",
        published_at=format_datetime(record.get("ngaySua")),
        summary_raw=build_summary(record),
    )


def get_record_datetime(record: dict[str, Any]) -> Optional[datetime]:
    for key in ["ngaySua", "ngayTao", "ngayLayYKien"]:
        parsed = try_parse_datetime(record.get(key))
        if parsed:
            return parsed
    return None


def get_furthest_page_date(records: list[dict[str, Any]]) -> Optional[datetime.date]:
    dates = [dt.date() for record in records if (dt := get_record_datetime(record))]
    if not dates:
        return None
    return min(dates)


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
    searchable_text = " ".join([article.title, article.summary_raw, article.source])

    legal_hits = keyword_hits(searchable_text, LEGAL_KEYWORDS)
    topic_hits = keyword_hits(searchable_text, TOPIC_KEYWORDS)

    if require_legal_keyword and not legal_hits:
        return False

    if require_topic_keyword and not topic_hits:
        return False

    return True


def article_to_json_dict(article: ParsedArticle) -> dict[str, Any]:
    return {
        "title": article.title,
        "url": article.url,
        "source": article.source,
        "published_at": article.published_at,
        "summary_raw": article.summary_raw,
    }


def fetch_document_page(
    session: requests.Session,
    offset: int,
    limit: int,
    date_from: str,
    date_to: str,
    txt_search: str = "",
    trang_thai: str = "-1",
) -> list[dict[str, Any]]:
    params = {
        "p_p_id": "VanBanDuThao_WAR_sdtvanbanportlet",
        "p_p_lifecycle": "2",
        "p_p_state": "normal",
        "p_p_mode": "view",
        "p_p_resource_id": "loadVanBanDuThao",
        "p_p_cacheability": "cacheLevelPage",
        "txtSearch": txt_search,
        "trangThai": trang_thai,
        "thoiGianTu": date_from,
        "thoiGianDen": date_to,
        "hinhThucVanBanId": "",
        "capBanHanhId": "undefined",
        "coQuanBanHanhId": "undefined",
        "offset": offset,
        "limit": limit,
    }
    response = session.get(API_LIST_URL, params=params, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return extract_items(response.json())


def crawl_vbdt_hcm(
    days: Optional[int] = 1,
    max_articles: int = 50,
    page_size: int = DEFAULT_LIMIT,
    max_pages: int = 10,
    date_from: str = "",
    date_to: str = "",
    txt_search: str = "",
    trang_thai: str = "-1",
    filter_relevant: bool = False,
    require_legal_keyword: bool = True,
    require_topic_keyword: bool = True,
) -> list[dict[str, Any]]:
    """
    Main function để đưa vào hệ thống.

    Returns:
        list[dict] theo format:
        {
          "title": "Số ký hiệu - Trích yếu",
          "url": "https://hochiminhcity.gov.vn/van-ban-du-thao?...&id=...",
          "source": "Tên cơ quan ban hành",
          "published_at": "2026-06-27 08:30",
          "summary_raw": "Trích yếu\\nNgày lấy ý kiến - Ngày hết hạn"
        }
    """
    logging.info("Start crawling HCMC draft legal documents")

    if date_from or date_to:
        api_date_from = normalize_api_date(date_from)
        api_date_to = normalize_api_date(date_to)
    else:
        api_date_from, api_date_to = get_date_range(days)
    start_date = parse_api_date(api_date_from)

    session = requests.Session()
    session.headers.update(HEADERS)

    results: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for page_no in range(max_pages):
        if len(results) >= max_articles:
            break

        offset = page_no * page_size

        try:
            logging.info(
                "Fetching HCMC draft docs offset=%s limit=%s from=%s to=%s",
                offset,
                page_size,
                api_date_from,
                api_date_to,
            )
            records = fetch_document_page(
                session=session,
                offset=offset,
                limit=page_size,
                date_from=api_date_from,
                date_to=api_date_to,
                txt_search=txt_search,
                trang_thai=trang_thai,
            )

            if not records:
                logging.info("No records found at offset=%s", offset)
                break

            furthest_page_date = get_furthest_page_date(records)

            for record in records:
                if len(results) >= max_articles:
                    break

                article = parse_article_record(record)
                if not article.title:
                    logging.info("Skip document without title: %s", record)
                    continue

                dedupe_key = article.url or f"{article.title}:{article.published_at}"
                if dedupe_key in seen_keys:
                    continue
                seen_keys.add(dedupe_key)

                if filter_relevant and not is_relevant_article(
                    article,
                    require_legal_keyword=require_legal_keyword,
                    require_topic_keyword=require_topic_keyword,
                ):
                    logging.info("Skip irrelevant document: %s", article.title)
                    continue

                results.append(article_to_json_dict(article))

            time.sleep(POLITE_DELAY_SECONDS)

            if start_date and furthest_page_date and furthest_page_date < start_date:
                logging.info(
                    "Stop before next page because furthest page date %s is older than start date %s",
                    furthest_page_date,
                    start_date,
                )
                break

            if len(records) < page_size:
                break

        except Exception as exc:
            logging.warning("Failed offset=%s: %s", offset, exc)
            break

    logging.info("Finished. Parsed %d HCMC draft documents.", len(results))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crawl HCMC draft legal documents and export them as JSON."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=1,
        help="Lấy dữ liệu trong N ngày theo lịch gần nhất. Mặc định: 1 là hôm nay. Dùng --days 0 để bỏ lọc ngày.",
    )
    parser.add_argument(
        "--max-articles",
        type=int,
        default=50,
        help="Số văn bản tối đa trả về. Mặc định: 50.",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=DEFAULT_LIMIT,
        help="Số văn bản mỗi lần gọi API. Mặc định: 50.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=10,
        help="Số page tối đa. Mặc định: 10.",
    )
    parser.add_argument(
        "--date-from",
        type=str,
        default="",
        help="thoiGianTu truyền vào API, ví dụ 27/06/2026. Nếu bỏ trống sẽ tính theo --days.",
    )
    parser.add_argument(
        "--date-to",
        type=str,
        default="",
        help="thoiGianDen truyền vào API, ví dụ 27/06/2026. Nếu bỏ trống sẽ tính theo --days.",
    )
    parser.add_argument(
        "--txt-search",
        type=str,
        default="",
        help="txtSearch truyền vào API. Mặc định: rỗng.",
    )
    parser.add_argument(
        "--trang-thai",
        type=str,
        default="-1",
        help="trangThai truyền vào API. Mặc định: -1.",
    )
    parser.add_argument(
        "--filter-relevant",
        action="store_true",
        help="Bật lọc keyword pháp lý/chủ đề. Mặc định: tắt để lấy toàn bộ văn bản dự thảo.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="vbdt_hcm_articles.json",
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

    articles = crawl_vbdt_hcm(
        days=None if args.days == 0 else args.days,
        max_articles=args.max_articles,
        page_size=args.page_size,
        max_pages=args.max_pages,
        date_from=args.date_from,
        date_to=args.date_to,
        txt_search=args.txt_search,
        trang_thai=args.trang_thai,
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
