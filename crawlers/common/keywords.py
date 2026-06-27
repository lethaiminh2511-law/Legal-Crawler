from __future__ import annotations

from .text import normalize_for_search


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
    "sở hữu trí tuệ",
    "quyền sở hữu trí tuệ",
    "quyền tác giả",
    "bản quyền",
    "nhãn hiệu",
    "sáng chế",
]


def keyword_hits(text: str, keywords: list[str]) -> list[str]:
    haystack = normalize_for_search(text)
    hits = []

    for keyword in keywords:
        normalized_keyword = normalize_for_search(keyword)
        if normalized_keyword and normalized_keyword in haystack:
            hits.append(keyword)

    return sorted(set(hits))


def is_relevant_text(
    text: str,
    legal_keywords: list[str] | None = None,
    topic_keywords: list[str] | None = None,
    require_legal_keyword: bool = True,
    require_topic_keyword: bool = True,
) -> bool:
    legal_hits = keyword_hits(text, legal_keywords or LEGAL_KEYWORDS)
    topic_hits = keyword_hits(text, topic_keywords or TOPIC_KEYWORDS)

    if require_legal_keyword and not legal_hits:
        return False

    if require_topic_keyword and not topic_hits:
        return False

    return True
