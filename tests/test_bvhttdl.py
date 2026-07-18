import unittest
from unittest.mock import MagicMock, patch

from crawlers import bvhttdl


class BvhttdlCrawlerTest(unittest.TestCase):
    def test_build_listing_page_url_uses_section_and_page_number(self):
        self.assertEqual(
            bvhttdl.build_listing_page_url("van-ban-du-thao", 2),
            "https://bvhttdl.gov.vn/van-ban-du-thao?Page=2",
        )
        self.assertEqual(
            bvhttdl.build_listing_page_url("van-ban-quan-ly", 3),
            "https://bvhttdl.gov.vn/van-ban-quan-ly?Page=3",
        )

    def test_extract_article_links_keeps_bvhttdl_document_detail_urls(self):
        listing_html = """
            <a href="/van-ban-du-thao/lay-y-kien-du-thao-nghi-dinh-123.htm">Draft</a>
            <a href="/y-kien-cho-van-ban-du-thao?dtid=7726">Draft feedback</a>
            <a href="/van-ban-quan-ly/122602.htm">Managed document</a>
            <a href="/tin-tuc/some-news-456.htm">News</a>
            <a href="https://example.com/van-ban-quan-ly/1.htm">External</a>
        """

        self.assertEqual(
            bvhttdl.extract_article_links(
                listing_html,
                "https://bvhttdl.gov.vn/van-ban-du-thao?Page=1",
            ),
            [
                "https://bvhttdl.gov.vn/van-ban-du-thao/lay-y-kien-du-thao-nghi-dinh-123.htm",
                "https://bvhttdl.gov.vn/y-kien-cho-van-ban-du-thao?dtid=7726",
                "https://bvhttdl.gov.vn/van-ban-quan-ly/122602.htm",
            ],
        )

    def test_crawl_keeps_draft_feedback_page_without_topic_keyword(self):
        listing_html = """
            <article class="gyk-item">
              <div class="gyk-deadline">Thời hạn: <span>15/07/2026 - 13/08/2026</span></div>
              <h3 class="gyk-title">
                <a href="/y-kien-cho-van-ban-du-thao?dtid=7727" class="gyk-title-link">
                  Hồ sơ dự thảo Thông tư về phân cấp quản lý tổ chức cán bộ
                </a>
              </h3>
            </article>
            <article class="gyk-item">
              <div class="gyk-deadline">Thời hạn: <span>13/07/2026 - 23/07/2026</span></div>
              <h3 class="gyk-title">
                <a href="/y-kien-cho-van-ban-du-thao?dtid=7726" class="gyk-title-link">
                  Lấy ý kiến dự thảo Hồ sơ Thông tư sửa đổi, bổ sung một số điều
                  của Thông tư số 02/2019/TT-BTTTT ngày 08/3/2019
                </a>
              </h3>
            </article>
        """
        article_html = """
            <html>
              <body>
                <h1>
                  Lấy ý kiến dự thảo Hồ sơ Thông tư sửa đổi, bổ sung một số điều
                  của Thông tư số 02/2019/TT-BTTTT ngày 08/3/2019
                </h1>
              </body>
            </html>
        """
        other_article_html = """
            <html>
              <body>
                <h1>Hồ sơ dự thảo Thông tư về phân cấp quản lý tổ chức cán bộ</h1>
              </body>
            </html>
        """

        def fake_fetch_html(_session, url, **_kwargs):
            if url == bvhttdl.build_listing_page_url("van-ban-du-thao", 1):
                return listing_html
            if url == "https://bvhttdl.gov.vn/y-kien-cho-van-ban-du-thao?dtid=7726":
                return article_html
            if url == "https://bvhttdl.gov.vn/y-kien-cho-van-ban-du-thao?dtid=7727":
                return other_article_html
            return "<html></html>"

        with patch.object(bvhttdl.requests, "Session", return_value=MagicMock()):
            with patch.object(bvhttdl, "fetch_html", side_effect=fake_fetch_html):
                with patch.object(bvhttdl.time, "sleep"):
                    results = bvhttdl.crawl_bo_van_hoa_the_thao_du_lich(
                        target_date="13-07-2026",
                        max_articles=5,
                        max_pages=1,
                        filter_relevant=True,
                    )

        self.assertEqual(len(results), 1)
        self.assertEqual(
            results[0]["url"],
            "https://bvhttdl.gov.vn/y-kien-cho-van-ban-du-thao?dtid=7726",
        )
        self.assertEqual(results[0]["published_at"], "2026-07-13 00:00")

    def test_crawl_parses_plain_draft_feedback_page_deadline(self):
        listing_html = """
            <a href="/y-kien-cho-van-ban-du-thao?dtid=7726">
                Lấy ý kiến dự thảo Hồ sơ Thông tư sửa đổi, bổ sung một số điều
                của Thông tư số 02/2019/TT-BTTTT ngày 08/3/2019
            </a>
        """
        article_html = """
            <html>
              <body>
                <h1>
                  Lấy ý kiến dự thảo Hồ sơ Thông tư sửa đổi, bổ sung một số điều
                  của Thông tư số 02/2019/TT-BTTTT ngày 08/3/2019
                </h1>
                <div>Thời hạn: 13/07/2026 - 23/07/2026</div>
              </body>
            </html>
        """

        def fake_fetch_html(_session, url, **_kwargs):
            if url == bvhttdl.build_listing_page_url("van-ban-du-thao", 1):
                return listing_html
            if url == "https://bvhttdl.gov.vn/y-kien-cho-van-ban-du-thao?dtid=7726":
                return article_html
            return "<html></html>"

        with patch.object(bvhttdl.requests, "Session", return_value=MagicMock()):
            with patch.object(bvhttdl, "fetch_html", side_effect=fake_fetch_html):
                with patch.object(bvhttdl.time, "sleep"):
                    results = bvhttdl.crawl_bo_van_hoa_the_thao_du_lich(
                        target_date="13-07-2026",
                        max_articles=5,
                        max_pages=1,
                        filter_relevant=True,
                    )

        self.assertEqual(len(results), 1)
        self.assertEqual(
            results[0]["url"],
            "https://bvhttdl.gov.vn/y-kien-cho-van-ban-du-thao?dtid=7726",
        )

    def test_crawl_keeps_draft_when_deadline_start_is_on_or_before_target_date(self):
        listing_html = """
            <article class="gyk-item">
              <div class="gyk-deadline">Thời hạn: <span>12/07/2026 - 22/07/2026</span></div>
              <h3 class="gyk-title">
                <a href="/y-kien-cho-van-ban-du-thao?dtid=7728" class="gyk-title-link">
                  Lấy ý kiến dự thảo Nghị định về bảo vệ dữ liệu cá nhân
                </a>
              </h3>
            </article>
        """
        article_html = """
            <html>
              <body>
                <h1>Lấy ý kiến dự thảo Nghị định về bảo vệ dữ liệu cá nhân</h1>
              </body>
            </html>
        """

        def fake_fetch_html(_session, url, **_kwargs):
            if url == bvhttdl.build_listing_page_url("van-ban-du-thao", 1):
                return listing_html
            if url == "https://bvhttdl.gov.vn/y-kien-cho-van-ban-du-thao?dtid=7728":
                return article_html
            return "<html></html>"

        with patch.object(bvhttdl.requests, "Session", return_value=MagicMock()):
            with patch.object(bvhttdl, "fetch_html", side_effect=fake_fetch_html):
                with patch.object(bvhttdl.time, "sleep"):
                    results = bvhttdl.crawl_bo_van_hoa_the_thao_du_lich(
                        target_date="18-07-2026",
                        max_articles=5,
                        max_pages=1,
                        filter_relevant=True,
                    )

        self.assertEqual(len(results), 1)
        self.assertEqual(
            results[0]["url"],
            "https://bvhttdl.gov.vn/y-kien-cho-van-ban-du-thao?dtid=7728",
        )

    def test_crawl_fetches_draft_and_management_listing_pages(self):
        draft_listing_html = """
            <a href="/van-ban-du-thao/lay-y-kien-du-thao-nghi-dinh-du-lieu-ca-nhan-123.htm">
                Lấy ý kiến dự thảo Nghị định về dữ liệu cá nhân
            </a>
        """
        management_listing_html = """
            <table>
              <tr>
                <td>1</td>
                <td>19/2026/TT-BVHTTDL</td>
                <td>
                  <a href="/van-ban-quan-ly/122602.htm">
                    Thông tư quy định về bảo vệ dữ liệu cá nhân
                  </a>
                </td>
                <td>Bộ Văn hóa, Thể thao và Du lịch</td>
                <td>18/07/2026</td>
              </tr>
            </table>
        """
        empty_listing_html = "<html></html>"
        draft_article_html = """
            <html>
              <head><meta name="description" content="Dự thảo nghị định về dữ liệu cá nhân"></head>
              <body>
                <h1>Lấy ý kiến dự thảo Nghị định về dữ liệu cá nhân</h1>
                <div>Thời hạn: 18/07/2026 - 28/07/2026</div>
              </body>
            </html>
        """
        management_article_html = """
            <html>
              <body>
                <h1>Thông tư quy định về bảo vệ dữ liệu cá nhân</h1>
                <dl>
                  <dt>Ngày ban hành</dt><dd>18/07/2026</dd>
                  <dt>Trích yếu</dt><dd>Ban hành thông tư về dữ liệu cá nhân</dd>
                </dl>
              </body>
            </html>
        """

        fetched_urls = []

        def fake_fetch_html(_session, url, **_kwargs):
            fetched_urls.append(url)
            if url == bvhttdl.build_listing_page_url("van-ban-du-thao", 1):
                return draft_listing_html
            if url == bvhttdl.build_listing_page_url("van-ban-quan-ly", 1):
                return management_listing_html
            if url.endswith("du-lieu-ca-nhan-123.htm"):
                return draft_article_html
            if url.endswith("122602.htm"):
                return management_article_html
            return empty_listing_html

        with patch.object(bvhttdl.requests, "Session", return_value=MagicMock()):
            with patch.object(bvhttdl, "fetch_html", side_effect=fake_fetch_html):
                with patch.object(bvhttdl.time, "sleep"):
                    results = bvhttdl.crawl_bo_van_hoa_the_thao_du_lich(
                        target_date="18-07-2026",
                        max_articles=5,
                        max_pages=2,
                        filter_relevant=True,
                    )

        self.assertEqual(len(results), 2)
        self.assertIn(
            "https://bvhttdl.gov.vn/van-ban-du-thao?Page=1",
            fetched_urls,
        )
        self.assertIn(
            "https://bvhttdl.gov.vn/van-ban-quan-ly?Page=1",
            fetched_urls,
        )


if __name__ == "__main__":
    unittest.main()
