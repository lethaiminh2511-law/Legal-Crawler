import json
import tempfile
import unittest
from pathlib import Path

from crawlers.common.dates import VN_TZ, format_datetime, is_within_days, try_parse_datetime
from crawlers.common.io import write_json
from crawlers.common.keywords import LEGAL_KEYWORDS, TOPIC_KEYWORDS, is_relevant_text, keyword_hits
from crawlers.common.models import ParsedArticle, article_to_json_dict
from crawlers.common.text import clean_text, normalize_for_search


class CommonUtilsTest(unittest.TestCase):
    def test_clean_text_normalizes_common_noise(self):
        self.assertEqual(clean_text(None), "")
        self.assertEqual(clean_text(" A\xa0  B\nC "), "A B C")
        self.assertEqual(clean_text("<p>Hello</p> <b>world</b>"), "Hello world")

    def test_normalize_for_search_lowercases_clean_text(self):
        self.assertEqual(normalize_for_search("  DỰ   THẢO "), "dự thảo")

    def test_try_parse_datetime_accepts_current_formats(self):
        cases = [
            "27/06/2026 08:30",
            "27-06-2026 08:30:12",
            "2026-06-27T08:30:12",
            "2026-06-27T08:30:12Z",
            "2026-06-27",
        ]
        for raw in cases:
            with self.subTest(raw=raw):
                parsed = try_parse_datetime(raw)
                self.assertIsNotNone(parsed)
                self.assertEqual(parsed.tzinfo, VN_TZ)

    def test_format_datetime_returns_project_format(self):
        self.assertEqual(format_datetime("27/06/2026 08:30"), "2026-06-27 08:30")
        self.assertIsNone(format_datetime(""))

    def test_is_within_days_keeps_unknown_dates(self):
        self.assertTrue(is_within_days(None, 7))

    def test_keyword_relevance_can_require_legal_and_topic_hits(self):
        text = "Dự thảo nghị định về dữ liệu cá nhân"
        self.assertEqual(keyword_hits(text, ["nghị định", "thông tư"]), ["nghị định"])
        self.assertTrue(
            is_relevant_text(
                text,
                legal_keywords=["nghị định"],
                topic_keywords=["dữ liệu cá nhân"],
            )
        )
        self.assertFalse(
            is_relevant_text(
                "Tin hoạt động chung",
                legal_keywords=["nghị định"],
                topic_keywords=["dữ liệu cá nhân"],
            )
        )

    def test_default_keywords_match_tracked_topics(self):
        self.assertEqual(
            LEGAL_KEYWORDS,
            [
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
            ],
        )
        self.assertEqual(
            TOPIC_KEYWORDS,
            [
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
            ],
        )

    def test_article_to_json_dict_preserves_existing_shape(self):
        article = ParsedArticle(
            title="Title",
            url="https://example.test/a",
            source="Source",
            published_at="2026-06-27 08:30",
            summary_raw="Summary",
        )
        self.assertEqual(
            article_to_json_dict(article),
            {
                "title": "Title",
                "url": "https://example.test/a",
                "source": "Source",
                "published_at": "2026-06-27 08:30",
                "summary_raw": "Summary",
            },
        )

    def test_write_json_outputs_utf8_pretty_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "articles.json"
            write_json([{"title": "Dự thảo"}], output)
            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8"))[0]["title"],
                "Dự thảo",
            )


if __name__ == "__main__":
    unittest.main()
