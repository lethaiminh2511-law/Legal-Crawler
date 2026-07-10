import unittest
from datetime import datetime
from unittest.mock import Mock

from crawlers import mof


class MofCrawlerTest(unittest.TestCase):
    def test_extract_listing_articles_from_api_payload(self):
        payload = {
            "data": [
                {
                    "title": "Dự thảo Nghị định về chính sách thuế",
                    "slug": "du-thao-nghi-dinh-ve-chinh-sach-thue",
                    "publishDate": "2026-06-24T09:30:00",
                    "description": "Bộ Tài chính lấy ý kiến dự thảo văn bản quy phạm pháp luật.",
                },
                {
                    "name": "Thông báo không có liên kết",
                    "publishTime": "24/06/2026",
                },
            ]
        }

        articles = mof.extract_listing_articles(payload, category_id="category-1")

        self.assertEqual(len(articles), 2)
        self.assertEqual(articles[0].title, "Dự thảo Nghị định về chính sách thuế")
        self.assertEqual(
            articles[0].url,
            "https://mof.gov.vn/webcenter/portal/btcvn/pages_r/l/tin-bo-tai-chinh?"
            "dDocName=du-thao-nghi-dinh-ve-chinh-sach-thue",
        )
        self.assertEqual(articles[0].published_at, "2026-06-24 09:30")
        self.assertEqual(
            articles[0].summary_raw,
            "Bộ Tài chính lấy ý kiến dự thảo văn bản quy phạm pháp luật.",
        )
        self.assertEqual(articles[0].category_url, mof.build_category_url("category-1"))
        self.assertEqual(articles[1].published_at, "2026-06-24 00:00")

    def test_extract_listing_articles_accepts_content_wrapper_and_absolute_url(self):
        payload = {
            "content": [
                {
                    "articleTitle": "Chính sách mới về phí và lệ phí",
                    "url": "https://mof.gov.vn/webcenter/portal/btcvn/pages_r/l/tin-bo-tai-chinh/chinh-sach-moi",
                    "createdDate": "2026-06-24 08:00:00",
                    "summary": "Quy định mới về phí.",
                }
            ]
        }

        articles = mof.extract_listing_articles(payload, category_id="category-2")

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].url, payload["content"][0]["url"])
        self.assertEqual(articles[0].published_at, "2026-06-24 08:00")

    def test_crawl_mof_posts_each_default_category_and_dedupes(self):
        session = Mock()
        session.headers = {}

        responses = []
        for title in ["Dự thảo Luật Thuế", "Dự thảo Luật Thuế", "Nghị định tài chính"]:
            response = Mock()
            response.json.return_value = {
                "data": [
                    {
                        "title": title,
                        "id": title.lower().replace(" ", "-"),
                        "publishDate": "2026-06-24T09:30:00",
                        "description": "Dự thảo chính sách pháp luật về tài chính.",
                    }
                ]
            }
            response.raise_for_status.return_value = None
            responses.append(response)

        session.post.side_effect = responses

        articles = mof.crawl_mof(
            days=1,
            max_articles=10,
            items_per_page=1,
            max_pages_per_category=1,
            filter_relevant=False,
            session=session,
            now=datetime(2026, 6, 24, 12, 0, tzinfo=mof.VN_TZ),
        )

        self.assertEqual(session.post.call_count, len(mof.DEFAULT_CATEGORY_IDS))
        posted_category_ids = [
            call.kwargs["json"]["categoryId"] for call in session.post.call_args_list
        ]
        self.assertEqual(posted_category_ids, mof.DEFAULT_CATEGORY_IDS)
        self.assertEqual([article["title"] for article in articles], ["Dự thảo Luật Thuế", "Nghị định tài chính"])

    def test_date_window_matches_ipvn_calendar_day_semantics(self):
        now = datetime(2026, 6, 24, 18, 0, tzinfo=mof.VN_TZ)

        self.assertTrue(mof.is_within_days("2026-06-24 00:00", days=1, now=now))
        self.assertFalse(mof.is_within_days("2026-06-23 23:59", days=1, now=now))
        self.assertTrue(mof.is_within_days(None, days=1, now=now))


if __name__ == "__main__":
    unittest.main()
