from __future__ import annotations

from .text import normalize_for_search


LEGAL_KEYWORDS = [
    "dự thảo",
    "lấy ý kiến",
    "góp ý dự thảo",
    "luật",
    "pháp lệnh",
    "nghị định",
    "thông tư",
    "quyết định",
    "nghị quyết",
    "chỉ thị",
    "ban hành",
    "có hiệu lực",
    "sửa đổi,bổ sung",
    "bãi bỏ",
    "hướng dẫn thi hành",
    "quy định chi tiết",
    "xử phạt",
    "vi phạm hành chính",
    "thủ tục hành chính",
    "thanh tra",
    "hậu kiểm",
]

TOPIC_KEYWORDS = [
    "bảo mật dữ liệu",
    "dữ liệu cá nhân",
    "bảo vệ dữ liệu cá nhân",
    "thu thập dữ liệu",
    "chia sẻ dữ liệu",
    "khai thác dữ liệu",
    "quản trị dữ liệu",
    "quyền riêng tư",
    "bảo mật thông tin",
    "vi phạm dữ liệu",
    "an ninh mạng",
    "mã độc",
    "tấn công mạng",
    "trí tuệ nhân tạo",
    "huấn luyện trí tuệ nhân tạo",
    "tác phẩm do trí tuệ nhân tạo",
    "chuyển đổi số",
    "kinh tế số",
    "công nghệ số",
    "công nghệ cao",
    "ứng dụng di động",
    "khoa học, công nghệ và đổi mới sáng tạo",
    "công nghiệp công nghệ số",
    "định danh và xác thực điện tử",
    "công nghiệp văn hóa",
    "luật cạnh tranh",
    "luật bảo vệ quyền lợi người tiêu dùng",
    "nền tảng số",
    "nền tảng trực tuyến",
    "nền tảng trung gian",
    "dịch vụ số",
    "dịch vụ số xuyên biên giới",
    "dịch vụ trung gian",
    "dịch vụ lưu trữ",
    "dịch vụ truyền hình",
    "nội dung số",
    "dịch vụ viễn thông",
    "doanh nghiệp viễn thông",
    "cung cấp dịch vụ viễn thông",
    "giao dịch xuyên biên giới",
    "dịch vụ xuyên biên giới",
    "dịch vụ số xuyên biên giới",
    "cung cấp dịch vụ xuyên biên giới",
    "quảng cáo xuyên biên giới",
    "thương mại điện tử",
    "giao dịch điện tử",
    "hợp đồng điện tử",
    "luật quảng cáo",
    "quảng cáo trực tuyến",
    "quảng cáo trên mạng",
    "quảng cáo xuyên biên giới",
    "nội dung quảng cáo",
    "kiểm duyệt nội dung",
    "thông tin sai sự thật",
    "tin giả",
    "sở hữu trí tuệ",
    "quyền sở hữu trí tuệ",
    "quyền tác giả",
    "quyền liên quan",
    "bản quyền",
    "tác phẩm số",
    "sao chép tác phẩm",
    "sử dụng tác phẩm",
    "phân phối tác phẩm",
    "nhãn hiệu",
    "sáng chế",
    "kiểu dáng công nghiệp",
    "bí mật kinh doanh",
    "chỉ dẫn địa lý",
    "đơn đăng ký sở hữu công nghiệp",
    "hàng giả",
    "bản quyền phần mềm",
    "cấp phép bản quyền",
    "giấy phép sử dụng nội dung",
    "tiền bản quyền",
    "quyền sao chép tạm thời",
    "ngoại lệ quyền tác giả",
    "giới hạn quyền tác giả",
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
