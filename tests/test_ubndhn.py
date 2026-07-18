import unittest
from datetime import datetime
from unittest.mock import Mock

from crawlers import ubndhn


LISTING_HTML = """
<div class="news-item" data-id="4260710091642503">
  <div class="news-info">
    <a href="/chi-dao-cua-ubnd-thanh-pho-ha-noi/ban-hanh-quy-dinh-4260710091642503.htm"
       title="Ban hành Quy định về chính sách pháp luật">
      <h3 class="news-title">Ban hành Quy định về chính sách pháp luật</h3>
    </a>
    <span class="news-time" title="13:37, 10/07/2026">8 giờ trước</span>
    <p class="news-sapo">HNP - UBND Thành phố ban hành quyết định mới.</p>
  </div>
</div>
<div class="news-item" data-id="missing-title">
  <div class="news-info"><a href="/bad.htm"></a></div>
</div>
"""

DOCUMENT_LISTING_HTML = """
<div class="UIDocumentList_Default">
  <table id="ctrl_213896_1252_gr_items">
    <tr>
      <th class="CodeClass"><span>Số ký hiệu</span></th>
      <th class="EpitomizeClass"><span>Trích yếu</span></th>
      <th class="ViewClass"><span>Nội dung chi tiết</span></th>
      <th class="DateOfIssuedClass"><span>Ngày ban hành</span></th>
    </tr>
    <tr>
      <td>
        <a href="/van-ban-quy-pham-phap-luat/quyet-dinh-100-261746"
           title="Về việc bãi bỏ quyết định"><span>100/2026/QĐ-UBND</span></a>
      </td>
      <td>
        <h7><a href="/van-ban-quy-pham-phap-luat/quyet-dinh-100-261746"
               title="Về việc bãi bỏ quyết định">Về việc bãi bỏ quyết định</a></h7>
      </td>
      <td><a class="desktop" href="/van-ban-quy-pham-phap-luat/quyet-dinh-100-261746">Xem chi tiết</a></td>
      <td><span class="date-pub">14/07/2026</span></td>
    </tr>
    <tr class="tr-pager"><td colspan="4">1 2 3</td></tr>
  </table>
</div>
"""


DETAIL_HTML = """
<html>
  <head>
    <meta name="description" content="Chi tiết quyết định và chính sách pháp luật.">
    <script type="application/ld+json">
      {
        "@type": "NewsArticle",
        "headline": "Ban hành Quy định chi tiết",
        "datePublished": "2026-07-10T13:37:00+07:00"
      }
    </script>
  </head>
  <body>
    <h1>Ban hành Quy định chi tiết</h1>
  </body>
</html>
"""


class UbndhnCrawlerTest(unittest.TestCase):
    def test_extract_listing_articles_from_news_zone_fragment(self):
        articles = ubndhn.extract_listing_articles(LISTING_HTML)

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].title, "Ban hành Quy định về chính sách pháp luật")
        self.assertEqual(
            articles[0].url,
            "https://hanoi.gov.vn/chi-dao-cua-ubnd-thanh-pho-ha-noi/ban-hanh-quy-dinh-4260710091642503.htm",
        )
        self.assertEqual(articles[0].published_at, "2026-07-10 13:37")
        self.assertEqual(articles[0].summary_raw, "HNP - UBND Thành phố ban hành quyết định mới.")
        self.assertEqual(articles[0].category_url, ubndhn.DEFAULT_CATEGORY_URL)

    def test_extract_listing_articles_from_document_table(self):
        category_url = "https://vanban.hanoi.gov.vn/van-ban-quy-pham-phap-luat"

        articles = ubndhn.extract_listing_articles(DOCUMENT_LISTING_HTML, category_url=category_url)

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].title, "Về việc bãi bỏ quyết định")
        self.assertEqual(
            articles[0].url,
            "https://vanban.hanoi.gov.vn/van-ban-quy-pham-phap-luat/quyet-dinh-100-261746",
        )
        self.assertEqual(articles[0].published_at, "2026-07-14 00:00")
        self.assertEqual(articles[0].summary_raw, "100/2026/QĐ-UBND")
        self.assertEqual(articles[0].category_url, category_url)

    def test_parse_article_detail_prefers_detail_fields_with_listing_fallback(self):
        fallback = ubndhn.extract_listing_articles(LISTING_HTML)[0]

        article = ubndhn.parse_article_detail(DETAIL_HTML, fallback=fallback)

        self.assertEqual(article.title, "Ban hành Quy định chi tiết")
        self.assertEqual(article.published_at, "2026-07-10 13:37")
        self.assertEqual(article.summary_raw, "Chi tiết quyết định và chính sách pháp luật.")
        self.assertEqual(article.category_url, fallback.category_url)

    def test_crawl_ubndhn_posts_zero_based_page_index_and_dedupes(self):
        session = Mock()
        session.headers = {}

        first = Mock()
        first.text = LISTING_HTML
        first.raise_for_status.return_value = None
        second = Mock()
        second.text = LISTING_HTML.replace("4260710091642503", "4260710091642504")
        second.raise_for_status.return_value = None

        session.post.side_effect = [first, second]

        articles = ubndhn.crawl_ubndhn(
            days=1,
            max_articles=10,
            max_pages=2,
            category_urls=[ubndhn.DEFAULT_CATEGORY_URL],
            filter_relevant=False,
            fetch_details=False,
            session=session,
            now=datetime(2026, 7, 10, 20, 0, tzinfo=ubndhn.VN_TZ),
        )

        self.assertEqual(session.post.call_count, 2)
        self.assertEqual(
            [call.kwargs["data"]["PageIndex"] for call in session.post.call_args_list],
            ["0", "1"],
        )
        self.assertEqual(len(articles), 2)
        self.assertEqual(articles[0]["title"], "Ban hành Quy định về chính sách pháp luật")

    def test_crawl_ubndhn_fetches_each_default_category(self):
        session = Mock()
        session.headers = {}

        post_response = Mock()
        post_response.text = LISTING_HTML
        post_response.raise_for_status.return_value = None

        get_response = Mock()
        get_response.text = DOCUMENT_LISTING_HTML
        get_response.raise_for_status.return_value = None

        other_get_response = Mock()
        other_get_response.text = DOCUMENT_LISTING_HTML.replace(
            "van-ban-quy-pham-phap-luat/quyet-dinh-100-261746",
            "van-ban-chi-dao-dieu-hanh/ke-hoach-281-261878",
        ).replace(
            "Về việc bãi bỏ quyết định",
            "Kế hoạch tổ chức lễ kỷ niệm",
        ).replace("100/2026/QĐ-UBND", "281/KH-UBND")
        other_get_response.raise_for_status.return_value = None

        session.post.return_value = post_response
        session.get.side_effect = [get_response, other_get_response]

        articles = ubndhn.crawl_ubndhn(
            days=30,
            max_articles=10,
            max_pages=1,
            filter_relevant=False,
            fetch_details=False,
            session=session,
            now=datetime(2026, 7, 14, 20, 0, tzinfo=ubndhn.VN_TZ),
        )

        self.assertEqual(session.post.call_count, 1)
        self.assertEqual(
            [call.args[0] for call in session.get.call_args_list],
            [
                "https://vanban.hanoi.gov.vn/van-ban-quy-pham-phap-luat",
                "https://vanban.hanoi.gov.vn/van-ban-chi-dao-dieu-hanh",
            ],
        )
        self.assertEqual([article["category_url"] for article in articles], ubndhn.DEFAULT_CATEGORY_URLS)

    def test_date_window_matches_ipvn_calendar_day_semantics(self):
        now = datetime(2026, 7, 10, 18, 0, tzinfo=ubndhn.VN_TZ)

        self.assertTrue(ubndhn.is_within_days("2026-07-10 00:00", days=1, now=now))
        self.assertFalse(ubndhn.is_within_days("2026-07-09 23:59", days=1, now=now))
        self.assertTrue(ubndhn.is_within_days(None, days=1, now=now))


if __name__ == "__main__":
    unittest.main()
