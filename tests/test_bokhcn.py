import unittest
from unittest.mock import MagicMock, patch

from crawlers import bokhcn


class BoKhcnTimelineTest(unittest.TestCase):
    def test_build_timeline_page_url_uses_category_and_page_number(self):
        self.assertEqual(
            bokhcn.build_timeline_page_url("100", 2),
            "https://mst.gov.vn/timeline-van-ban/100/2.htm",
        )

    def test_crawl_fetches_timeline_legal_document_pages(self):
        date_listing_html = """
            <a href="/tin-tuc-su-kien/tin-ngay-123456.htm">News</a>
        """
        timeline_listing_html = """
            <div class="document-item">
              <a href="/van-ban-phap-luat/14973.htm">Legal</a>
              <span class="date">18/07/2026</span>
            </div>
        """
        empty_listing_html = "<html></html>"
        news_article_html = """
            <html>
              <head><meta name="description" content="Ban hành nghị định về dữ liệu cá nhân"></head>
              <body>
                <h1>Nghị định về bảo vệ dữ liệu cá nhân</h1>
                <time datetime="2026-07-18T08:00:00+07:00"></time>
              </body>
            </html>
        """
        legal_document_html = """
            <html>
              <body>
                <h1>Thông tư số 01/VBHN-BTTTT</h1>
                <dl>
                  <dt>Số hiệu</dt><dd>01/VBHN-BTTTT</dd>
                  <dt>Cơ quan ban hành</dt><dd>Bộ Thông tin và Truyền thông</dd>
                  <dt>Hình thức văn bản</dt><dd>Thông tư</dd>
                  <dt>Lĩnh vực</dt><dd>Xuất bản, in và phát hành</dd>
                  <dt>Trích yếu nội dung</dt>
                  <dd>Ban hành thông tư về bảo vệ dữ liệu cá nhân</dd>
                  <dt>Ngày ban hành</dt><dd>18/07/2026</dd>
                </dl>
              </body>
            </html>
        """

        fetched_urls = []

        def fake_fetch_html(_session, url, **_kwargs):
            fetched_urls.append(url)
            if url == bokhcn.build_date_page_url("18-07-2026"):
                return date_listing_html
            if url.endswith("-123456.htm"):
                return news_article_html
            if url == "https://mst.gov.vn/van-ban-phap-luat/14973.htm":
                return legal_document_html
            if "/timeline-van-ban/" in url:
                category = url.split("/timeline-van-ban/", 1)[1].split("/", 1)[0]
                page = int(url.rsplit("/", 1)[1].removesuffix(".htm"))
                if category in {"100", "101", "2"} and page == 1:
                    return timeline_listing_html
                return empty_listing_html
            return empty_listing_html

        with patch.object(bokhcn.requests, "Session", return_value=MagicMock()):
            with patch.object(bokhcn, "fetch_html", side_effect=fake_fetch_html):
                with patch.object(bokhcn.time, "sleep"):
                    results = bokhcn.crawl_bo_khoa_hoc_cong_nghe(
                        target_date="18-07-2026",
                        max_articles=2,
                        filter_relevant=True,
                    )

        self.assertEqual(len(results), 2)
        self.assertIn("https://mst.gov.vn/timeline-van-ban/100/1.htm", fetched_urls)
        self.assertIn("https://mst.gov.vn/timeline-van-ban/101/1.htm", fetched_urls)
        self.assertIn("https://mst.gov.vn/timeline-van-ban/2/1.htm", fetched_urls)
        legal_document = next(
            item
            for item in results
            if item["url"] == "https://mst.gov.vn/van-ban-phap-luat/14973.htm"
        )
        self.assertEqual(legal_document["code"], "01/VBHN-BTTTT")
        self.assertEqual(legal_document["agency"], "Bộ Thông tin và Truyền thông")
        self.assertEqual(legal_document["document_type"], "Thông tư")
        self.assertEqual(legal_document["field"], "Xuất bản, in và phát hành")
        self.assertEqual(legal_document["summary_raw"], "Ban hành thông tư về bảo vệ dữ liệu cá nhân")
        self.assertEqual(legal_document["issued_date"], "18/07/2026")
        self.assertEqual(legal_document["published_at"], "2026-07-18 00:00")

    def test_parse_legal_document_metadata_fields(self):
        article = bokhcn.parse_article(
            """
            <html>
              <body>
                <div><span>Số hiệu</span><span>3125/QĐ-BKHCN</span></div>
                <div><span>Cơ quan ban hành</span><span>Bộ Khoa học và Công nghệ</span></div>
                <div><span>Hình thức văn bản</span><span>Quyết định</span></div>
                <div><span>Lĩnh vực</span><span>Viễn thông, tần số vô tuyến điện</span></div>
                <div><span>Trích yếu nội dung</span><span>Quyết định về dữ liệu cá nhân</span></div>
                <div><span>Ngày ban hành</span><span>15/07/2026</span></div>
              </body>
            </html>
            """,
            "https://mst.gov.vn/van-ban-phap-luat/14973.htm",
        )

        self.assertEqual(article.code, "3125/QĐ-BKHCN")
        self.assertEqual(article.agency, "Bộ Khoa học và Công nghệ")
        self.assertEqual(article.document_type, "Quyết định")
        self.assertEqual(article.field, "Viễn thông, tần số vô tuyến điện")
        self.assertEqual(article.summary_raw, "Quyết định về dữ liệu cá nhân")
        self.assertEqual(article.issued_date, "15/07/2026")

    def test_crawl_filters_old_legal_documents_from_timeline_listing(self):
        current_url = "https://mst.gov.vn/van-ban-phap-luat/100.htm"
        old_url = "https://mst.gov.vn/van-ban-phap-luat/99.htm"
        later_url = "https://mst.gov.vn/van-ban-phap-luat/98.htm"
        timeline_listing_html = f"""
            <div class="document-item">
              <a href="{current_url}">Current</a>
              <span class="date">18/07/2026</span>
            </div>
            <div class="document-item">
              <a href="{old_url}">Old</a>
              <span class="date">17/07/2026</span>
            </div>
            <div class="document-item">
              <a href="{later_url}">Later</a>
              <span class="date">16/07/2026</span>
            </div>
        """
        empty_listing_html = "<html></html>"

        def build_document_html(code: str, issued_date: str) -> str:
            return f"""
                <html>
                  <body>
                    <h1>Quyết định về bảo vệ dữ liệu cá nhân</h1>
                    <dl>
                      <dt>Số hiệu</dt><dd>{code}</dd>
                      <dt>Cơ quan ban hành</dt><dd>Bộ Khoa học và Công nghệ</dd>
                      <dt>Hình thức văn bản</dt><dd>Quyết định</dd>
                      <dt>Lĩnh vực</dt><dd>Dữ liệu</dd>
                      <dt>Trích yếu nội dung</dt>
                      <dd>Quyết định về bảo vệ dữ liệu cá nhân</dd>
                      <dt>Ngày ban hành</dt><dd>{issued_date}</dd>
                    </dl>
                  </body>
                </html>
            """

        fetched_urls = []

        def fake_fetch_html(_session, url, **_kwargs):
            fetched_urls.append(url)
            if url == bokhcn.build_date_page_url("18-07-2026"):
                return empty_listing_html
            if url == bokhcn.build_timeline_page_url("100", 1):
                return timeline_listing_html
            if "/timeline-van-ban/" in url:
                return empty_listing_html
            if url == current_url:
                return build_document_html("100/QĐ-BKHCN", "18/07/2026")
            if url == old_url:
                return build_document_html("99/QĐ-BKHCN", "17/07/2026")
            if url == later_url:
                raise AssertionError("Crawler should stop before fetching later old documents")
            return empty_listing_html

        with patch.object(bokhcn.requests, "Session", return_value=MagicMock()):
            with patch.object(bokhcn, "fetch_html", side_effect=fake_fetch_html):
                with patch.object(bokhcn.time, "sleep"):
                    results = bokhcn.crawl_bo_khoa_hoc_cong_nghe(
                        target_date="18-07-2026",
                        max_articles=10,
                        filter_relevant=True,
                    )

        self.assertEqual([item["code"] for item in results], ["100/QĐ-BKHCN"])
        self.assertNotIn(old_url, fetched_urls)
        self.assertNotIn(later_url, fetched_urls)

    def test_timeline_listing_filters_links_by_target_date_before_fetching_detail(self):
        target_url = "https://mst.gov.vn/van-ban-phap-luat/200.htm"
        old_url = "https://mst.gov.vn/van-ban-phap-luat/199.htm"
        future_url = "https://mst.gov.vn/van-ban-phap-luat/201.htm"
        timeline_listing_html = f"""
            <div class="document-item">
              <a href="{target_url}">Quyết định đúng ngày</a>
              <span class="date">18/07/2026</span>
            </div>
            <div class="document-item">
              <a href="{old_url}">Quyết định cũ</a>
              <span class="date">17/07/2026</span>
            </div>
            <div class="document-item">
              <a href="{future_url}">Quyết định ngày khác</a>
              <span class="date">19/07/2026</span>
            </div>
        """
        empty_listing_html = "<html></html>"
        legal_document_html = """
            <html>
              <body>
                <h1>Quyết định về bảo vệ dữ liệu cá nhân</h1>
                <dl>
                  <dt>Số hiệu</dt><dd>200/QĐ-BKHCN</dd>
                  <dt>Cơ quan ban hành</dt><dd>Bộ Khoa học và Công nghệ</dd>
                  <dt>Hình thức văn bản</dt><dd>Quyết định</dd>
                  <dt>Lĩnh vực</dt><dd>Dữ liệu</dd>
                  <dt>Trích yếu nội dung</dt>
                  <dd>Quyết định về bảo vệ dữ liệu cá nhân</dd>
                  <dt>Ngày ban hành</dt><dd>18/07/2026</dd>
                </dl>
              </body>
            </html>
        """

        fetched_urls = []

        def fake_fetch_html(_session, url, **_kwargs):
            fetched_urls.append(url)
            if url == bokhcn.build_date_page_url("18-07-2026"):
                return empty_listing_html
            if url == bokhcn.build_timeline_page_url("100", 1):
                return timeline_listing_html
            if "/timeline-van-ban/" in url:
                return empty_listing_html
            if url == target_url:
                return legal_document_html
            if url in {old_url, future_url}:
                raise AssertionError("Crawler should filter timeline URLs before detail fetch")
            return empty_listing_html

        with patch.object(bokhcn.requests, "Session", return_value=MagicMock()):
            with patch.object(bokhcn, "fetch_html", side_effect=fake_fetch_html):
                with patch.object(bokhcn.time, "sleep"):
                    results = bokhcn.crawl_bo_khoa_hoc_cong_nghe(
                        target_date="18-07-2026",
                        max_articles=10,
                        filter_relevant=True,
                    )

        self.assertEqual([item["url"] for item in results], [target_url])
        self.assertNotIn(old_url, fetched_urls)
        self.assertNotIn(future_url, fetched_urls)

    def test_crawl_continues_timeline_pages_when_earlier_page_has_only_newer_dates(self):
        newer_url = "https://mst.gov.vn/van-ban-phap-luat/301.htm"
        target_url = "https://mst.gov.vn/van-ban-phap-luat/300.htm"
        first_timeline_page = f"""
            <div class="document-item">
              <a href="{newer_url}">Quyết định mới hơn ngày cần crawl</a>
              <span class="date">19/07/2026</span>
            </div>
        """
        second_timeline_page = f"""
            <div class="document-item">
              <a href="{target_url}">Quyết định đúng ngày</a>
              <span class="date">18/07/2026</span>
            </div>
        """
        legal_document_html = """
            <html>
              <body>
                <h1>Quyết định về bảo vệ dữ liệu cá nhân</h1>
                <dl>
                  <dt>Số hiệu</dt><dd>300/QĐ-BKHCN</dd>
                  <dt>Cơ quan ban hành</dt><dd>Bộ Khoa học và Công nghệ</dd>
                  <dt>Hình thức văn bản</dt><dd>Quyết định</dd>
                  <dt>Lĩnh vực</dt><dd>Dữ liệu</dd>
                  <dt>Trích yếu nội dung</dt>
                  <dd>Quyết định về bảo vệ dữ liệu cá nhân</dd>
                  <dt>Ngày ban hành</dt><dd>18/07/2026</dd>
                </dl>
              </body>
            </html>
        """

        fetched_urls = []

        def fake_fetch_html(_session, url, **_kwargs):
            fetched_urls.append(url)
            if url == bokhcn.build_date_page_url("18-07-2026"):
                return "<html></html>"
            if url == bokhcn.build_timeline_page_url("100", 1):
                return first_timeline_page
            if url == bokhcn.build_timeline_page_url("100", 2):
                return second_timeline_page
            if "/timeline-van-ban/" in url:
                return "<html></html>"
            if url == target_url:
                return legal_document_html
            if url == newer_url:
                raise AssertionError("Crawler should not fetch newer off-target detail")
            return "<html></html>"

        with patch.object(bokhcn.requests, "Session", return_value=MagicMock()):
            with patch.object(bokhcn, "fetch_html", side_effect=fake_fetch_html):
                with patch.object(bokhcn.time, "sleep"):
                    results = bokhcn.crawl_bo_khoa_hoc_cong_nghe(
                        target_date="18-07-2026",
                        max_articles=10,
                        filter_relevant=True,
                    )

        self.assertEqual([item["url"] for item in results], [target_url])
        self.assertIn(bokhcn.build_timeline_page_url("100", 2), fetched_urls)
        self.assertNotIn(newer_url, fetched_urls)


if __name__ == "__main__":
    unittest.main()
