import unittest
from unittest.mock import patch

from crawlers import bocongan


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"data": {"content": []}}


class FakeSession:
    def __init__(self):
        self.headers = {}
        self.requests = []

    def get(self, url, params, timeout):
        self.requests.append({"url": url, "params": params, "timeout": timeout})
        return FakeResponse()


class BoCongAnCrawlerTest(unittest.TestCase):
    def test_fetch_draft_document_page_sends_res_type_and_run_date_start_from(self):
        session = FakeSession()

        bocongan.fetch_draft_document_page(
            session=session,
            page=0,
            size=20,
            start_from="2026-08-21 00:00:00",
        )

        self.assertEqual(
            session.requests,
            [
                {
                    "url": "https://api-portal.bocongan.gov.vn/backend-portal/draft-document",
                    "params": {
                        "page": 0,
                        "size": 20,
                        "resType": 1,
                        "startFrom": "2026-08-21 00:00:00",
                    },
                    "timeout": bocongan.REQUEST_TIMEOUT,
                }
            ],
        )

    def test_crawl_fetches_draft_documents_from_run_date_with_size_20(self):
        requested_sizes = []

        def fake_fetch_draft_document_page(session, page, size, start_from):
            requested_sizes.append(size)
            self.assertEqual(page, 0)
            self.assertEqual(start_from, "2026-08-14 00:00:00")
            return [
                {
                    "title": "Dự thảo nghị định về bảo vệ dữ liệu cá nhân",
                    "url": "/du-thao-nghi-dinh-du-lieu-ca-nhan",
                    "summary": "Lấy ý kiến bảo vệ dữ liệu cá nhân",
                    "createdAt": "2026-08-21 09:00:00",
                }
            ]

        with patch.object(bocongan.requests, "Session", return_value=FakeSession()):
            with patch.object(
                bocongan,
                "fetch_draft_document_page",
                side_effect=fake_fetch_draft_document_page,
            ):
                with patch.object(bocongan, "fetch_category_page", return_value=[]):
                    with patch.object(bocongan.time, "sleep"):
                        articles = bocongan.crawl_bo_cong_an(
                            category_ids=[1065],
                            days=7,
                            max_articles=5,
                            run_date="2026-08-21",
                        )

        self.assertEqual(requested_sizes, [20])
        self.assertEqual(len(articles), 1)
        self.assertEqual(
            articles[0]["url"],
            "https://bocongan.gov.vn/du-thao-nghi-dinh-du-lieu-ca-nhan",
        )
        self.assertEqual(articles[0]["published_at"], "2026-08-21 09:00")
        self.assertEqual(articles[0]["category_id"], bocongan.DRAFT_DOCUMENT_CATEGORY_ID)


if __name__ == "__main__":
    unittest.main()
