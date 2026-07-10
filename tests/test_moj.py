import unittest
from datetime import datetime

from crawlers import moj


LISTING_HTML = """
<html>
  <body>
    <nav>
      <a href="/portal/tin-tuc/chuyen-muc/van-ban-chinh-sach-moi.html">Category</a>
      <a href="/portal/tin-tuc/chi-tiet/chuc-nang-nhiem-vu-t36zx7.html">Chức năng nhiệm vụ</a>
    </nav>
    <div class="news-list">
      <article>
        <h4>
          <a href="/portal/tin-tuc/chi-tiet/du-an-luat-do-thi-dac-biet-th4xod7c7f.html">
            Dự án Luật Đô thị đặc biệt
          </a>
        </h4>
        <p>24/06/2026</p>
        <div class="desc">Xây dựng cơ chế, chính sách đặc thù cho Thành phố Hồ Chí Minh.</div>
      </article>
      <article>
        <h4>
          <a href="/portal/tin-tuc/chi-tiet/du-an-luat-do-thi-dac-biet-th4xod7c7f.html">
            Dự án Luật Đô thị đặc biệt
          </a>
        </h4>
        <span>24/06/2026</span>
        <p>Duplicate link should be ignored.</p>
      </article>
    </div>
  </body>
</html>
"""


DETAIL_HTML = """
<html>
  <head>
    <meta name="description" content="Chi tiết về dự án luật và chính sách mới.">
  </head>
  <body>
    <h1>Dự án Luật Đô thị đặc biệt: Xây dựng cơ chế, chính sách đặc thù</h1>
    <div class="date">24/06/2026</div>
  </body>
</html>
"""


class MojCrawlerTest(unittest.TestCase):
    def test_extract_listing_articles_keeps_article_links_only_and_dedupes(self):
        articles = moj.extract_listing_articles(
            LISTING_HTML,
            category_url="https://moj.gov.vn/portal/tin-tuc/chuyen-muc/chi-dao-dieu-hanh-cua-lanh-dao-bo.html",
        )

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].title, "Dự án Luật Đô thị đặc biệt")
        self.assertEqual(
            articles[0].url,
            "https://moj.gov.vn/portal/tin-tuc/chi-tiet/du-an-luat-do-thi-dac-biet-th4xod7c7f.html",
        )
        self.assertEqual(articles[0].published_at, "2026-06-24 00:00")
        self.assertEqual(
            articles[0].summary_raw,
            "Xây dựng cơ chế, chính sách đặc thù cho Thành phố Hồ Chí Minh.",
        )

    def test_parse_article_detail_prefers_detail_fields_with_listing_fallback(self):
        fallback = moj.extract_listing_articles(LISTING_HTML, "https://moj.gov.vn/category.html")[0]

        article = moj.parse_article_detail(DETAIL_HTML, fallback=fallback)

        self.assertEqual(
            article.title,
            "Dự án Luật Đô thị đặc biệt: Xây dựng cơ chế, chính sách đặc thù",
        )
        self.assertEqual(article.published_at, "2026-06-24 00:00")
        self.assertEqual(article.summary_raw, "Chi tiết về dự án luật và chính sách mới.")
        self.assertEqual(article.category_url, fallback.category_url)

    def test_date_window_matches_ipvn_calendar_day_semantics(self):
        now = datetime(2026, 6, 24, 18, 0, tzinfo=moj.VN_TZ)

        self.assertTrue(moj.is_within_days("2026-06-24 00:00", days=1, now=now))
        self.assertFalse(moj.is_within_days("2026-06-23 23:59", days=1, now=now))
        self.assertTrue(moj.is_within_days(None, days=1, now=now))

    def test_article_to_json_dict_includes_category_url(self):
        article = moj.ParsedArticle(
            title="Title",
            url="https://moj.gov.vn/portal/tin-tuc/chi-tiet/title.html",
            source=moj.SOURCE_NAME,
            published_at="2026-06-24 00:00",
            summary_raw="Summary",
            category_url="https://moj.gov.vn/category.html",
        )

        self.assertEqual(
            moj.article_to_json_dict(article),
            {
                "title": "Title",
                "url": "https://moj.gov.vn/portal/tin-tuc/chi-tiet/title.html",
                "source": moj.SOURCE_NAME,
                "published_at": "2026-06-24 00:00",
                "summary_raw": "Summary",
                "category_url": "https://moj.gov.vn/category.html",
            },
        )


if __name__ == "__main__":
    unittest.main()
