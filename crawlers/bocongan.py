from __future__ import annotations

import argparse
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests


VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

SOURCE_NAME = "Cổng thông tin điện tử Bộ Công an"
BASE_SITE_URL = "https://bocongan.gov.vn/"
API_SEARCH_URL = "https://api-portal.bocongan.gov.vn/backend-portal/articles/search"

DEFAULT_CATEGORY_IDS = [1065, 1066, 1067]

HEADERS = {
    "accept": "*/*",
    "accept-language": "en,vi;q=0.9,en-US;q=0.8",
    "origin": "https://bocongan.gov.vn",
    "portal-id": "25",
    "referer": "https://bocongan.gov.vn/",
    "sec-ch-ua": '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/148.0.0.0 Safari/537.36"
    ),
}

# Cookie này lấy từ curl user cung cấp. Nếu hết hạn, chạy lại với cookie mới bằng --cookie "...".
DEFAULT_COOKIE = (
    "visid_incap_3245975=Qmavt10tSoWcs0HFCdIPvp79L2oAAAAAQUIPAAAAAAAR7+kev6zh72/VXj0RtRtH; "
    "incap_ses_445_3245975=FROSXPSaiwW4zCcAaPUsBp79L2oAAAAAvPD03bATxWaanNTj25/4zQ==; "
    "visid_incap_3244786=hN9tsAXqS5iN4AwN6iQKvKD9L2oAAAAAQUIPAAAAAACIQBx8h+p7DnVr40dUgM6H; "
    "incap_ses_310_3244786=rv7+bwQKnVQndAfi8ldNBKH9L2oAAAAABdpKUCG58Ap+q9rOCEVqJg==; "
    "_ga=GA1.1.956250340.1781530018; "
    "incap_ses_310_3245975=zbhEKdxTVSXEOgvi8ldNBGYBMGoAAAAAkdQ3D4RnDVnfMELuWwwcGw==; "
    "_ga_P7QQZWHF3X=GS2.1.s1781530018$o1$g1$t1781531298$j60$l0$h0"
)

REQUEST_TIMEOUT = 25
POLITE_DELAY_SECONDS = 0.6


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
    "bảo vệ dữ liệu cá nhân",
    "xử lý dữ liệu cá nhân",
    "chuyển dữ liệu cá nhân ra nước ngoài",
    "thu thập thông tin",
    "thu thập dữ liệu",
    "chia sẻ dữ liệu",
    "khai thác dữ liệu",
    "dữ liệu mở",
    "dữ liệu lớn",
    "quản trị dữ liệu",
    "trung tâm dữ liệu",
    "điện toán đám mây",
    "quyền riêng tư",
    "đời sống riêng tư",
    "bí mật cá nhân",
    "bảo mật thông tin",
    "an toàn thông tin",
    "an ninh mạng",
    "rò rỉ dữ liệu",
    "vi phạm dữ liệu",
    "trí tuệ nhân tạo",
    "hệ thống trí tuệ nhân tạo",
    "mô hình trí tuệ nhân tạo",
    "mô hình ngôn ngữ lớn",
    "dữ liệu huấn luyện",
    "nội dung do trí tuệ nhân tạo tạo ra",
    "tác phẩm do trí tuệ nhân tạo tạo ra",
    "giả mạo bằng công nghệ",
    "thuật toán",
    "tự động hóa",
    "khai thác văn bản và dữ liệu",
    "chuyển đổi số",
    "kinh tế số",
    "xã hội số",
    "công nghệ số",
    "công nghệ mới",
    "công nghệ cao",
    "công nghệ chiến lược",
    "luật công nghệ",
    "nền tảng số",
    "nền tảng trực tuyến",
    "nền tảng trung gian",
    "dịch vụ số",
    "dịch vụ số xuyên biên giới",
    "dịch vụ xuyên biên giới",
    "giao dịch xuyên biên giới",
    "cung cấp dịch vụ xuyên biên giới",
    "mạng xã hội",
    "ứng dụng di động",
    "phần mềm",
    "bản quyền phần mềm",
    "hệ thống thông tin",
    "thương mại điện tử",
    "sàn giao dịch thương mại điện tử",
    "website thương mại điện tử",
    "giao dịch điện tử",
    "hợp đồng điện tử",
    "chữ ký điện tử",
    "chữ ký số",
    "dịch vụ chứng thực chữ ký số",
    "định danh điện tử",
    "xác thực điện tử",
    "tài khoản định danh điện tử",
    "thanh toán điện tử",
    "trung gian thanh toán",
    "ví điện tử",
    "quảng cáo trực tuyến",
    "quảng cáo trên mạng",
    "quảng cáo xuyên biên giới",
    "nội dung quảng cáo",
    "người nổi tiếng",
    "người có ảnh hưởng",
    "phát trực tiếp",
    "bán hàng qua phát trực tiếp",
    "nội dung vi phạm",
    "gỡ bỏ nội dung",
    "kiểm duyệt nội dung",
    "thông tin sai sự thật",
    "tin giả",
    "sở hữu trí tuệ",
    "quyền sở hữu trí tuệ",
    "quyền tác giả",
    "quyền liên quan",
    "bản quyền",
    "tác phẩm",
    "tác phẩm số",
    "nội dung số",
    "sao chép tác phẩm",
    "sử dụng tác phẩm",
    "truyền đạt tác phẩm",
    "phân phối tác phẩm",
    "xâm phạm quyền tác giả",
    "xâm phạm quyền sở hữu trí tuệ",
    "thực thi quyền sở hữu trí tuệ",
    "giám định sở hữu trí tuệ",
    "nhãn hiệu",
    "sáng chế",
    "kiểu dáng công nghiệp",
    "bí mật kinh doanh",
    "chỉ dẫn địa lý",
    "giống cây trồng",
    "đơn đăng ký sở hữu công nghiệp",
    "hàng giả",
    "hàng hóa giả mạo nhãn hiệu",
    "huấn luyện trí tuệ nhân tạo",
    "sử dụng tác phẩm để huấn luyện trí tuệ nhân tạo",
    "dữ liệu huấn luyện trí tuệ nhân tạo",
    "cấp phép bản quyền",
    "giấy phép sử dụng nội dung",
    "tiền bản quyền",
    "quyền sao chép tạm thời",
    "ngoại lệ quyền tác giả",
    "giới hạn quyền tác giả",
    "dịch vụ viễn thông",
    "mạng Internet",
    "tên miền",
    "địa chỉ giao thức mạng",
    "dịch vụ trung gian",
    "dịch vụ lưu trữ",
    "dịch vụ mạng xã hội",
    "dịch vụ chia sẻ video",
    "dịch vụ nội dung thông tin trên mạng",
    "trò chơi điện tử trên mạng",
    "dịch vụ truyền hình, phim và nội dung trên Internet",
    "kiểm tra an ninh mạng",
    "đánh giá an ninh mạng",
    "bảo vệ hệ thống thông tin",
    "hệ thống thông tin quan trọng",
    "ứng cứu sự cố",
    "sự cố an toàn thông tin",
    "mã độc",
    "tấn công mạng",
    "lỗ hổng bảo mật",
    "kiểm thử xâm nhập",
]


@dataclass
class ParsedArticle:
    title: str
    url: str
    source: str
    published_at: Optional[str]
    summary_raw: str
    category_id: int


def clean_text(text: Optional[Any]) -> str:
    if text is None:
        return ""
    text = str(text).replace("\xa0", " ")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_for_search(text: str) -> str:
    return clean_text(text).lower()


def try_parse_datetime(raw: Optional[Any]) -> Optional[datetime]:
    raw_text = clean_text(raw)
    if not raw_text:
        return None

    # Epoch milliseconds / seconds
    if re.fullmatch(r"\d{10,13}", raw_text):
        timestamp = int(raw_text)
        if len(raw_text) == 13:
            timestamp = timestamp / 1000
        return datetime.fromtimestamp(timestamp, tz=VN_TZ)

    candidates = [
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d/%m/%Y",
        "%Y-%m-%d",
    ]

    # Chuẩn hóa timezone dạng Z
    if raw_text.endswith("Z"):
        raw_text = raw_text[:-1] + "+0000"

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


def first_present(record: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return None


def build_article_url(record: dict[str, Any]) -> str:
    raw_url = first_present(
        record,
        [
            "url",
            "link",
            "href",
            "path",
            "detailUrl",
            "detail_url",
            "shareUrl",
            "share_url",
            "canonicalUrl",
            "canonical_url",
        ],
    )

    if raw_url:
        raw_url = clean_text(raw_url)
        if raw_url.startswith("http"):
            return raw_url
        return urljoin(BASE_SITE_URL, raw_url.lstrip("/"))

    slug = first_present(record, ["slug", "alias", "seoAlias", "seo_alias"])
    article_id = first_present(record, ["id", "articleId", "article_id", "newsId", "news_id"])

    if slug and article_id:
        return urljoin(BASE_SITE_URL, f"{clean_text(slug)}-{clean_text(article_id)}.html")
    if slug:
        return urljoin(BASE_SITE_URL, clean_text(slug).lstrip("/"))
    if article_id:
        return urljoin(BASE_SITE_URL, f"article-{clean_text(article_id)}.html")

    return ""


def extract_items(payload: Any) -> list[dict[str, Any]]:
    """
    API có thể trả về nhiều shape khác nhau, ví dụ:
    - {"data": {"content": [...]}}
    - {"data": {"items": [...]}}
    - {"content": [...]}
    - [...] 
    Hàm này cố lấy đúng list bài viết một cách linh hoạt.
    """
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if not isinstance(payload, dict):
        return []

    direct_list_keys = ["content", "items", "data", "rows", "results", "list", "articles"]
    for key in direct_list_keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    nested_dict_keys = ["data", "result", "page", "payload"]
    for key in nested_dict_keys:
        value = payload.get(key)
        if isinstance(value, dict):
            items = extract_items(value)
            if items:
                return items

    return []


def parse_article_record(record: dict[str, Any], category_id: int) -> ParsedArticle:
    title = clean_text(first_present(record, ["title", "name", "subject", "headline"]))
    summary_raw = clean_text(
        first_present(
            record,
            [
                "summary",
                "description",
                "desc",
                "sapo",
                "lead",
                "intro",
                "shortDescription",
                "short_description",
            ],
        )
    )
    published_at = format_datetime(
        first_present(
            record,
            [
                "publishedAt",
                "published_at",
                "publishDate",
                "publish_date",
                "publishedDate",
                "published_date",
                "createdAt",
                "created_at",
                "createdDate",
                "created_date",
                "date",
                "displayDate",
                "display_date",
            ],
        )
    )

    return ParsedArticle(
        title=title,
        url=build_article_url(record),
        source=SOURCE_NAME,
        published_at=published_at,
        summary_raw=summary_raw,
        category_id=category_id,
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
        # Không parse được ngày thì vẫn giữ lại để tránh miss bài quan trọng
        return True

    parsed = try_parse_datetime(published_at)
    if not parsed:
        return True

    cutoff = datetime.now(VN_TZ) - timedelta(days=days)
    return parsed >= cutoff


def article_to_json_dict(article: ParsedArticle) -> dict[str, Any]:
    return {
        "title": article.title,
        "url": article.url,
        "source": article.source,
        "published_at": article.published_at,
        "summary_raw": article.summary_raw,
        "category_id": article.category_id,
    }


def fetch_category_page(
    session: requests.Session,
    category_id: int,
    page: int,
    size: int,
    date_from: str = "",
    date_to: str = "",
) -> list[dict[str, Any]]:
    params = {
        "dateFrom": date_from,
        "dateTo": date_to,
        "category_id": category_id,
        "page": page,
        "size": size,
    }
    response = session.get(API_SEARCH_URL, params=params, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return extract_items(response.json())


def crawl_bo_cong_an(
    category_ids: Optional[list[int]] = None,
    days: Optional[int] = 7,
    max_articles: int = 50,
    page_size: int = 10,
    max_pages_per_category: int = 5,
    date_from: str = "",
    date_to: str = "",
    filter_relevant: bool = True,
    require_legal_keyword: bool = True,
    require_topic_keyword: bool = True,
    cookie: Optional[str] = DEFAULT_COOKIE,
) -> list[dict[str, Any]]:
    """
    Main function để đưa vào hệ thống.

    Returns:
        list[dict] theo format:
        {
          "title": "...",
          "url": "...",
          "source": "Cổng thông tin điện tử Bộ Công an",
          "published_at": "2026-06-15 08:30",
          "summary_raw": "...",
          "category_id": 1065
        }
    """
    logging.info("Start crawling Bo Cong An API")

    category_ids = category_ids or DEFAULT_CATEGORY_IDS
    session = requests.Session()
    session.headers.update(HEADERS)
    if cookie:
        session.headers.update({"cookie": cookie})

    results: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for category_id in category_ids:
        logging.info("Start category_id=%s", category_id)

        for page in range(max_pages_per_category):
            if len(results) >= max_articles:
                break

            try:
                logging.info("Fetching category_id=%s page=%s size=%s", category_id, page, page_size)
                records = fetch_category_page(
                    session=session,
                    category_id=category_id,
                    page=page,
                    size=page_size,
                    date_from=date_from,
                    date_to=date_to,
                )

                if not records:
                    logging.info("No records for category_id=%s page=%s", category_id, page)
                    break

                for record in records:
                    if len(results) >= max_articles:
                        break

                    article = parse_article_record(record, category_id=category_id)

                    if not article.title:
                        logging.info("Skip article without title: %s", record)
                        continue

                    dedupe_key = article.url or f"{article.category_id}:{article.title}:{article.published_at}"
                    if dedupe_key in seen_keys:
                        continue
                    seen_keys.add(dedupe_key)

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

                time.sleep(POLITE_DELAY_SECONDS)

                if len(records) < page_size:
                    break

            except Exception as exc:
                logging.warning("Failed category_id=%s page=%s: %s", category_id, page, exc)
                break

    logging.info("Finished. Parsed %d relevant articles.", len(results))
    return results


def parse_category_ids(raw: str) -> list[int]:
    return [int(item.strip()) for item in raw.split(",") if item.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crawl Bo Cong An API and export legal/IP-tech updates as JSON."
    )
    parser.add_argument(
        "--category-ids",
        type=str,
        default=",".join(str(item) for item in DEFAULT_CATEGORY_IDS),
        help="Danh sách category_id, ngăn cách bằng dấu phẩy. Mặc định: 1065,1066,1067.",
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
        "--page-size",
        type=int,
        default=10,
        help="Số bài mỗi page API. Mặc định: 10.",
    )
    parser.add_argument(
        "--max-pages-per-category",
        type=int,
        default=5,
        help="Số page tối đa cho mỗi category_id. Mặc định: 5.",
    )
    parser.add_argument(
        "--date-from",
        type=str,
        default="",
        help="dateFrom truyền vào API, ví dụ 2026-06-01. Mặc định: rỗng như curl.",
    )
    parser.add_argument(
        "--date-to",
        type=str,
        default="",
        help="dateTo truyền vào API, ví dụ 2026-06-15. Mặc định: rỗng như curl.",
    )
    parser.add_argument(
        "--cookie",
        type=str,
        default=DEFAULT_COOKIE,
        help="Cookie lấy từ browser/curl. Nếu cookie default hết hạn thì paste cookie mới vào đây.",
    )
    parser.add_argument(
        "--no-filter",
        action="store_true",
        help="Không lọc keyword; lấy tất cả bài từ 3 category_id.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="bocongan_articles.json",
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

    articles = crawl_bo_cong_an(
        category_ids=parse_category_ids(args.category_ids),
        days=None if args.days == 0 else args.days,
        max_articles=args.max_articles,
        page_size=args.page_size,
        max_pages_per_category=args.max_pages_per_category,
        date_from=args.date_from,
        date_to=args.date_to,
        filter_relevant=not args.no_filter,
        require_legal_keyword=True,
        require_topic_keyword=True,
        cookie=args.cookie,
    )

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)

    if args.pretty:
        print(json.dumps(articles, ensure_ascii=False, indent=2))

    print(f"Saved {len(articles)} articles to {args.output}")


if __name__ == "__main__":
    main()
