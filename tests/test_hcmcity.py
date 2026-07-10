import unittest
from unittest.mock import Mock

from crawlers import hcmcity


LISTING_HTML = """
<div class="news-items row">
  <div class="news-item col-lg-6">
    <div class="d-md-block d-none img-hover mb-3">
      <a href="/web/hcm/-/sample-article" class="d-flex w-100 same-height text-decoration-none">
        <p class="asset-publisher-title" title="Triển khai thi hành Luật mới">Triển khai thi hành Luật mới</p>
        <div class="limit-tin-descc-news"><p>(Hochiminhcity.gov.vn) - Nội dung về chuyển đổi số.</p></div>
        <span class="text-date-sklh">15:55 | 10/07/2026</span>
      </a>
    </div>
    <div class="d-md-none d-block img-hover mb-3">
      <a href="/web/hcm/-/sample-article" class="row same-height text-decoration-none">
        <p class="asset-publisher-title">Triển khai thi hành Luật mới</p>
        <div class="limit-tin-descc-news"><p>Bản mobile trùng.</p></div>
        <span>15:55 | 10/07/2026</span>
      </a>
    </div>
  </div>
</div>
"""


class HcmCityCrawlerTest(unittest.TestCase):
    def test_build_listing_url_increments_asset_publisher_page_index(self):
        self.assertEqual(
            hcmcity.build_listing_url(hcmcity.DEFAULT_PREFIXES[0], page_no=2),
            "https://hochiminhcity.gov.vn/tin-t%E1%BB%A9c-s%E1%BB%B1-ki%E1%BB%87n-all-?"
            "_com_liferay_asset_publisher_web_portlet_AssetPublisherPortlet_INSTANCE_iwwYBC4Hj8wV_cur=2",
        )

    def test_extract_listing_articles_dedupes_desktop_and_mobile_cards(self):
        articles = hcmcity.extract_listing_articles(LISTING_HTML, hcmcity.DEFAULT_PREFIXES[0])

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].title, "Triển khai thi hành Luật mới")
        self.assertEqual(
            articles[0].url,
            "https://hochiminhcity.gov.vn/web/hcm/-/sample-article",
        )
        self.assertEqual(articles[0].published_at, "2026-07-10 15:55")
        self.assertEqual(
            articles[0].summary_raw,
            "(Hochiminhcity.gov.vn) - Nội dung về chuyển đổi số.",
        )

    def test_crawl_hcmcity_fetches_page_one_and_dedupes_results(self):
        session = Mock()
        session.headers = {}
        response = Mock()
        response.text = LISTING_HTML
        response.encoding = "utf-8"
        response.raise_for_status.return_value = None
        session.get.return_value = response

        articles = hcmcity.crawl_hcmcity(
            days=None,
            max_articles=5,
            max_pages_per_prefix=1,
            filter_relevant=False,
            fetch_details=False,
            session=session,
        )

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["title"], "Triển khai thi hành Luật mới")
        fetched_url = session.get.call_args.kwargs["url"]
        self.assertIn(
            "_com_liferay_asset_publisher_web_portlet_AssetPublisherPortlet_INSTANCE_iwwYBC4Hj8wV_cur=1",
            fetched_url,
        )


if __name__ == "__main__":
    unittest.main()
