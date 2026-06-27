import json
import tempfile
import unittest
from pathlib import Path

from crawlers.common.dates import VN_TZ, format_datetime, is_within_days, try_parse_datetime
from crawlers.common.io import write_json
from crawlers.common.keywords import is_relevant_text, keyword_hits
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
