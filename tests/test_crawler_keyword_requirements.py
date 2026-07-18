import inspect
import unittest
from pathlib import Path

from crawlers.bokhcn import crawl_bo_khoa_hoc_cong_nghe
from crawlers.bokhcn import is_relevant_article as is_relevant_bokhcn
from crawlers.common.models import ParsedArticle as CommonArticle
from crawlers.duthaoonline import ParsedArticle as DuthaoOnlineArticle
from crawlers.duthaoonline import is_relevant_article as is_relevant_duthaoonline
from crawlers.vbdt_hcm import ParsedArticle as VbdtHcmArticle
from crawlers.vbdt_hcm import crawl_vbdt_hcm
from crawlers.vbdt_hcm import is_relevant_article as is_relevant_vbdt_hcm
from crawlers.vibonline import ParsedArticle as VibOnlineArticle
from crawlers.vibonline import is_relevant_article as is_relevant_vibonline
from crawlers.vbcp import ParsedDocument, is_relevant_document


class CrawlerKeywordRequirementsTest(unittest.TestCase):
    def test_draft_crawlers_require_legal_and_topic_keywords_by_default(self):
        cases = [
            (
                is_relevant_bokhcn,
                CommonArticle(
                    title="Dự thảo nghị định mới",
                    url="https://example.test/legal-only",
                    source="Test",
                    published_at=None,
                    summary_raw="Lấy ý kiến góp ý dự thảo",
                ),
                CommonArticle(
                    title="Bảo vệ dữ liệu cá nhân",
                    url="https://example.test/topic-only",
                    source="Test",
                    published_at=None,
                    summary_raw="Quản trị dữ liệu và quyền riêng tư",
                ),
                CommonArticle(
                    title="Dự thảo nghị định về dữ liệu cá nhân",
                    url="https://example.test/both",
                    source="Test",
                    published_at=None,
                    summary_raw="Lấy ý kiến bảo vệ dữ liệu cá nhân",
                ),
            ),
            (
                is_relevant_duthaoonline,
                DuthaoOnlineArticle(
                    title="Dự thảo nghị định mới",
                    url="https://example.test/legal-only",
                    source="Test",
                    published_at=None,
                    summary_raw="Lấy ý kiến góp ý dự thảo",
                    category="du-thao-luat",
                    status="Đang lấy ý kiến",
                    document_type="Dự thảo luật",
                ),
                DuthaoOnlineArticle(
                    title="Bảo vệ dữ liệu cá nhân",
                    url="https://example.test/topic-only",
                    source="Test",
                    published_at=None,
                    summary_raw="Quản trị dữ liệu và quyền riêng tư",
                    category="du-thao-luat",
                    status="Đang xử lý",
                    document_type="Tin chung",
                ),
                DuthaoOnlineArticle(
                    title="Dự thảo nghị định về dữ liệu cá nhân",
                    url="https://example.test/both",
                    source="Test",
                    published_at=None,
                    summary_raw="Lấy ý kiến bảo vệ dữ liệu cá nhân",
                    category="du-thao-luat",
                    status="Đang lấy ý kiến",
                    document_type="Dự thảo luật",
                ),
            ),
            (
                is_relevant_vbdt_hcm,
                VbdtHcmArticle(
                    title="Dự thảo nghị định mới",
                    url="https://example.test/legal-only",
                    source="Test",
                    published_at=None,
                    summary_raw="Lấy ý kiến góp ý dự thảo",
                ),
                VbdtHcmArticle(
                    title="Bảo vệ dữ liệu cá nhân",
                    url="https://example.test/topic-only",
                    source="Test",
                    published_at=None,
                    summary_raw="Quản trị dữ liệu và quyền riêng tư",
                ),
                VbdtHcmArticle(
                    title="Dự thảo nghị định về dữ liệu cá nhân",
                    url="https://example.test/both",
                    source="Test",
                    published_at=None,
                    summary_raw="Lấy ý kiến bảo vệ dữ liệu cá nhân",
                ),
            ),
            (
                is_relevant_vibonline,
                VibOnlineArticle(
                    title="Dự thảo nghị định mới",
                    url="https://example.test/legal-only",
                    source="Test",
                    published_at=None,
                    summary_raw="Lấy ý kiến góp ý dự thảo",
                    document_type="Dự thảo luật",
                ),
                VibOnlineArticle(
                    title="Bảo vệ dữ liệu cá nhân",
                    url="https://example.test/topic-only",
                    source="Test",
                    published_at=None,
                    summary_raw="Quản trị dữ liệu và quyền riêng tư",
                    document_type="Tin chung",
                ),
                VibOnlineArticle(
                    title="Dự thảo nghị định về dữ liệu cá nhân",
                    url="https://example.test/both",
                    source="Test",
                    published_at=None,
                    summary_raw="Lấy ý kiến bảo vệ dữ liệu cá nhân",
                    document_type="Dự thảo luật",
                ),
            ),
        ]

        for relevance_check, legal_only, topic_only, both in cases:
            with self.subTest(crawler=relevance_check.__module__):
                self.assertFalse(relevance_check(legal_only))
                self.assertFalse(relevance_check(topic_only))
                self.assertTrue(relevance_check(both))

    def test_vbcp_requires_legal_and_topic_keywords_by_default(self):
        legal_only = ParsedDocument(
            title="Nghị định mới",
            url="https://example.test/legal-only",
            source="Test",
            published_at=None,
            summary_raw="Ban hành quy định chi tiết",
        )
        topic_only = ParsedDocument(
            title="Bảo vệ dữ liệu cá nhân",
            url="https://example.test/topic-only",
            source="Test",
            published_at=None,
            summary_raw="Quản trị dữ liệu và quyền riêng tư",
        )
        both = ParsedDocument(
            title="Nghị định về dữ liệu cá nhân",
            url="https://example.test/both",
            source="Test",
            published_at=None,
            summary_raw="Ban hành quy định chi tiết về bảo vệ dữ liệu cá nhân",
        )

        self.assertFalse(is_relevant_document(legal_only))
        self.assertFalse(is_relevant_document(topic_only))
        self.assertTrue(is_relevant_document(both))

    def test_crawler_entrypoints_filter_relevance_by_default(self):
        for crawler in (crawl_bo_khoa_hoc_cong_nghe, crawl_vbdt_hcm):
            with self.subTest(crawler=crawler.__module__):
                signature = inspect.signature(crawler)
                self.assertIs(signature.parameters["filter_relevant"].default, True)

    def test_crawler_cli_paths_do_not_disable_keyword_filtering(self):
        forbidden_patterns = [
            "--no-filter",
            "--filter-relevant",
            "--require-topic-keyword",
            "filter_relevant=not args.no_filter",
            "filter_relevant=args.filter_relevant",
            "require_topic_keyword=args.require_topic_keyword",
        ]

        for crawler_path in Path("crawlers").glob("*.py"):
            if crawler_path.name == "__init__.py":
                continue

            source = crawler_path.read_text(encoding="utf-8")
            for pattern in forbidden_patterns:
                with self.subTest(crawler=crawler_path.name, pattern=pattern):
                    self.assertNotIn(pattern, source)


if __name__ == "__main__":
    unittest.main()
