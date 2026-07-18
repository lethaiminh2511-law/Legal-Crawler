from __future__ import annotations

from .text import normalize_for_search


LEGAL_KEYWORDS = ['dự thảo', 'lấy ý kiến', 'góp ý dự thảo', 'luật', 'pháp lệnh', 'nghị định', 'thông tư', 'quyết định', 'nghị quyết', 'chỉ thị', 'ban hành', 'có hiệu lực', 'sửa đổi, bổ sung', 'thay thế', 'bãi bỏ', 'hướng dẫn thi hành', 'quy định chi tiết', 'xử phạt', 'vi phạm hành chính', 'thủ tục hành chính', 'kiểm tra', 'thanh tra', 'hậu kiểm']

TOPIC_KEYWORDS = ['dữ liệu', 'data', 'dữ liệu cá nhân', 'bảo vệ dữ liệu cá nhân', 'xử lý dữ liệu cá nhân', 'thu thập thông tin', 'thu thập dữ liệu', 'chia sẻ dữ liệu', 'khai thác dữ liệu', 'dữ liệu mở', 'quản trị dữ liệu', 'trung tâm dữ liệu', 'điện toán đám mây', 'quyền riêng tư', 'bí mật cá nhân', 'bảo mật dữ liệu', 'bảo mật thông tin', 'rò rỉ dữ liệu', 'vi phạm dữ liệu', 'an toàn thông tin', 'an ninh mạng', 'kiểm tra an ninh mạng', 'bảo vệ hệ thống thông tin', 'hệ thống thông tin', 'ứng cứu sự cố', 'sự cố an toàn thông tin', 'mã độc', 'tấn công mạng', 'lỗ hổng bảo mật', 'trí tuệ nhân tạo', 'huấn luyện trí tuệ nhân tạo', 'tác phẩm do trí tuệ nhân tạo', 'mô hình ngôn ngữ lớn', 'dữ liệu huấn luyện', 'giả mạo bằng công nghệ', 'thuật toán', 'tự động hóa', 'khai thác văn bản và dữ liệu', 'chuyển đổi số', 'kinh tế số', 'xã hội số', 'công nghệ số', 'công nghệ mới', 'công nghệ cao', 'công nghệ chiến lược', 'khoa học, công nghệ và đổi mới sáng tạo', 'công nghiệp công nghệ số', 'công nghệ', 'phần mềm', 'ứng dụng di động', 'hệ thống thông tin', 'nền tảng số', 'nền tảng trực tuyến', 'nền tảng trung gian', 'dịch vụ số', 'dịch vụ số xuyên biên giới', 'dịch vụ trung gian', 'mạng xã hội', 'dịch vụ truyền hình', 'phim và nội dung trên Internet', 'nội dung số', 'giao dịch xuyên biên giới', 'dịch vụ xuyên biên giới', 'dịch vụ số xuyên biên giới', 'cung cấp dịch vụ xuyên biên giới', 'quảng cáo xuyên biên giới', 'thương mại điện tử', 'sàn giao dịch thương mại điện tử', 'giao dịch điện tử', 'hợp đồng điện tử', 'chữ ký điện tử', 'chữ ký số', 'dịch vụ chứng thực chữ ký số', 'định danh điện tử', 'xác thực điện tử', 'tài khoản định danh điện tử', 'thanh toán điện tử', 'trung gian thanh toán', 'ví điện tử', 'quảng cáo', 'luật quảng cáo', 'quảng cáo trực tuyến', 'quảng cáo trên mạng', 'quảng cáo xuyên biên giới', 'nội dung quảng cáo', 'phát trực tiếp', 'bán hàng qua phát trực tiếp', 'nội dung vi phạm', 'gỡ bỏ nội dung', 'kiểm duyệt nội dung', 'thông tin sai sự thật', 'tin giả', 'nội dung số', 'sở hữu trí tuệ', 'quyền sở hữu trí tuệ', 'quyền tác giả', 'quyền liên quan', 'bản quyền', 'tác phẩm số', 'nội dung số', 'sao chép tác phẩm', 'sử dụng tác phẩm', 'truyền đạt tác phẩm', 'phân phối tác phẩm', 'xâm phạm quyền tác giả', 'xâm phạm quyền sở hữu trí tuệ', 'thực thi quyền sở hữu trí tuệ', 'giám định sở hữu trí tuệ', 'nhãn hiệu', 'sáng chế', 'kiểu dáng công nghiệp', 'bí mật kinh doanh', 'chỉ dẫn địa lý', 'đơn đăng ký sở hữu công nghiệp', 'hàng giả', 'bản quyền phần mềm', 'cấp phép bản quyền', 'giấy phép sử dụng nội dung', 'tiền bản quyền', 'quyền sao chép tạm thời', 'ngoại lệ quyền tác giả', 'giới hạn quyền tác giả', 'dịch vụ viễn thông', 'doanh nghiệp viễn thông', 'cung cấp dịch vụ viễn thông', 'mạng Internet', 'tên miền', 'địa chỉ giao thức mạng', 'dịch vụ trung gian', 'dịch vụ lưu trữ', 'hệ thống thông tin']


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
