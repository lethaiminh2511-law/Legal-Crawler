import unittest
from unittest.mock import MagicMock, patch

from crawlers import bocongthuong


class BoCongThuongCrawlerTest(unittest.TestCase):
    def test_extract_draft_listing_articles_uses_start_date_and_deadline_summary(self):
        html = """
            <main>
              <h2>Các dự thảo đang lấy ý kiến góp ý</h2>
              <div class="draft-row">
                <a href="/du-thao-van-ban/draft-hoa-chat.html">
                  Dự thảo Nghị định sửa đổi quy định về Luật Hóa chất
                </a>
                <span>Ngày bắt đầu: 20/08/2026 - Ngày hết hạn: 07/09/2026</span>
                <a href="/gop-y?draft=1">Xem góp ý</a>
              </div>
            </main>
        """

        articles = bocongthuong.extract_draft_listing_articles(html)

        self.assertEqual(len(articles), 1)
        self.assertEqual(
            articles[0].url,
            "https://moit.gov.vn/du-thao-van-ban/draft-hoa-chat.html",
        )
        self.assertEqual(
            articles[0].title,
            "Dự thảo Nghị định sửa đổi quy định về Luật Hóa chất",
        )
        self.assertEqual(articles[0].published_at, "2026-08-20 00:00")
        self.assertEqual(
            articles[0].summary_raw,
            "Ngày bắt đầu: 20/08/2026 - Ngày hết hạn: 07/09/2026",
        )

    def test_extract_listing_articles_from_legal_document_table_rows(self):
        html = """
            <table>
              <tr>
                <th>STT</th>
                <th>Tên văn bản</th>
                <th>Số hiệu</th>
                <th>Ngày ban hành</th>
                <th>File đính kèm</th>
              </tr>
              <tr>
                <td>1</td>
                <td>
                  <a href="/van-ban-phap-luat/thong-tu-ve-thuong-mai-dien-tu.html">
                    Thông tư quy định chi tiết về thương mại điện tử
                  </a>
                </td>
                <td>43/2026/TT-BCT</td>
                <td>14/08/2026</td>
                <td><a href="/upload/file.pdf">PDF</a></td>
              </tr>
            </table>
        """

        articles = bocongthuong.extract_listing_articles(html)

        self.assertEqual(len(articles), 1)
        self.assertEqual(
            articles[0].url,
            "https://moit.gov.vn/van-ban-phap-luat/thong-tu-ve-thuong-mai-dien-tu.html",
        )
        self.assertEqual(
            articles[0].title,
            "Thông tư quy định chi tiết về thương mại điện tử",
        )
        self.assertEqual(articles[0].published_at, "2026-08-14 00:00")
        self.assertEqual(articles[0].summary_raw, "43/2026/TT-BCT")

    def test_crawl_fetches_news_and_legal_document_listings(self):
        class FakeResponse:
            def __init__(self, text):
                self.text = text
                self.encoding = "utf-8"
                self.apparent_encoding = "utf-8"

            def raise_for_status(self):
                return None

        news_html = """
            <article class="article-news">
              <a class="article-title" href="/tin-tuc/news-1.htm">
                Nghị định về bảo vệ dữ liệu cá nhân
              </a>
              <span class="article-date">24/06/2026 09:30</span>
              <div class="article-brief">Ban hành quy định về dữ liệu cá nhân.</div>
            </article>
        """
        legal_html = """
            <article class="article-news">
              <a class="article-title" href="/van-ban-phap-luat/legal-1.htm">
                Thông tư về thương mại điện tử
              </a>
              <span class="article-date">24/06/2026</span>
              <div class="article-brief">Hướng dẫn thi hành quy định thương mại điện tử.</div>
            </article>
        """

        session = MagicMock()
        session.headers = {}

        def fake_post(_url, params, data, timeout):
            if data["type"] == "Article.News":
                return FakeResponse(news_html)
            if data["type"] == "Article.LegalDocument":
                self.assertEqual(params[1], ("moduleId", "12"))
                self.assertEqual(data["categoryId"], "101788669")
                self.assertEqual(data["parentId"], "101788669")
                self.assertEqual(data["blockVB"], "1")
                return FakeResponse(legal_html)
            raise AssertionError(f"Unexpected listing type: {data['type']}")

        session.post.side_effect = fake_post

        with patch.object(bocongthuong.requests, "Session", return_value=session):
            with patch.object(bocongthuong.time, "sleep"):
                results = bocongthuong.crawl_bo_cong_thuong(
                    days=None,
                    max_articles=10,
                    items_per_page=12,
                    max_pages=1,
                    filter_relevant=True,
                    fetch_details=False,
                )

        self.assertEqual(session.post.call_count, 2)
        posted_types = [call.kwargs["data"]["type"] for call in session.post.call_args_list]
        self.assertEqual(posted_types, ["Article.News", "Article.LegalDocument"])
        self.assertEqual(
            [article["url"] for article in results],
            [
                "https://moit.gov.vn/tin-tuc/news-1.htm",
                "https://moit.gov.vn/van-ban-phap-luat/legal-1.htm",
            ],
        )

    def test_crawl_fetches_draft_document_listing(self):
        class FakeResponse:
            def __init__(self, text):
                self.text = text
                self.encoding = "utf-8"
                self.apparent_encoding = "utf-8"

            def raise_for_status(self):
                return None

        empty_html = "<html></html>"
        draft_html = """
            <div class="draft-row">
              <a href="/du-thao-van-ban/draft-hoa-chat.html">
                Dự thảo Nghị định sửa đổi quy định về thương mại điện tử
              </a>
              <span>Ngày bắt đầu: 20/08/2026 - Ngày hết hạn: 07/09/2026</span>
              <a href="/gop-y?draft=1">Xem góp ý</a>
            </div>
        """

        session = MagicMock()
        session.headers = {}
        session.post.return_value = FakeResponse(empty_html)
        session.get.return_value = FakeResponse(draft_html)

        with patch.object(bocongthuong.requests, "Session", return_value=session):
            with patch.object(bocongthuong.time, "sleep"):
                results = bocongthuong.crawl_bo_cong_thuong(
                    days=None,
                    max_articles=10,
                    items_per_page=12,
                    max_pages=1,
                    filter_relevant=True,
                    fetch_details=False,
                )

        session.get.assert_called_once_with(
            "https://moit.gov.vn/du-thao-van-ban",
            timeout=bocongthuong.REQUEST_TIMEOUT,
        )
        self.assertEqual(
            [article["url"] for article in results],
            ["https://moit.gov.vn/du-thao-van-ban/draft-hoa-chat.html"],
        )
        self.assertEqual(results[0]["published_at"], "2026-08-20 00:00")

    def test_crawl_fetches_legal_listing_even_when_news_reaches_article_limit(self):
        class FakeResponse:
            def __init__(self, text):
                self.text = text
                self.encoding = "utf-8"
                self.apparent_encoding = "utf-8"

            def raise_for_status(self):
                return None

        news_html = """
            <article class="article-news">
              <a class="article-title" href="/tin-tuc/news-1.htm">
                Nghị định về bảo vệ dữ liệu cá nhân
              </a>
              <span class="article-date">24/06/2026</span>
              <div class="article-brief">Ban hành quy định về dữ liệu cá nhân.</div>
            </article>
        """
        legal_html = """
            <tr>
              <td>1</td>
              <td>
                <a href="/van-ban-phap-luat/thong-tu-ve-thuong-mai-dien-tu.html">
                  Thông tư về thương mại điện tử
                </a>
              </td>
              <td>43/2026/TT-BCT</td>
              <td>14/08/2026</td>
              <td><a href="/upload/file.pdf">PDF</a></td>
            </tr>
        """

        session = MagicMock()
        session.headers = {}

        def fake_post(_url, params, data, timeout):
            if data["type"] == "Article.News":
                return FakeResponse(news_html)
            if data["type"] == "Article.LegalDocument":
                return FakeResponse(legal_html)
            raise AssertionError(f"Unexpected listing type: {data['type']}")

        session.post.side_effect = fake_post

        with patch.object(bocongthuong.requests, "Session", return_value=session):
            with patch.object(bocongthuong.time, "sleep"):
                results = bocongthuong.crawl_bo_cong_thuong(
                    days=None,
                    max_articles=1,
                    items_per_page=12,
                    max_pages=1,
                    filter_relevant=True,
                    fetch_details=False,
                )

        posted_types = [call.kwargs["data"]["type"] for call in session.post.call_args_list]
        self.assertEqual(posted_types, ["Article.News", "Article.LegalDocument"])
        self.assertEqual(len(results), 1)


if __name__ == "__main__":
    unittest.main()
