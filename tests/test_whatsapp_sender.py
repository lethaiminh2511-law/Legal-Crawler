import unittest
from datetime import datetime

from whatsapp_sender import VN_TZ, filter_items_by_window, resolve_window


class WhatsAppSenderWindowTests(unittest.TestCase):
    def test_morning_window_includes_previous_day_from_22_until_before_10(self):
        now = datetime(2026, 8, 15, 10, 0, tzinfo=VN_TZ)
        items = [
            {"title": "before previous evening boundary", "published_at": "2026-08-14 21:59"},
            {"title": "previous evening boundary", "published_at": "2026-08-14 22:00"},
            {"title": "overnight item", "published_at": "2026-08-15 09:59"},
            {"title": "current morning boundary", "published_at": "2026-08-15 10:00"},
        ]

        selected = filter_items_by_window(items, "morning", now=now)

        self.assertEqual(
            [item["title"] for item in selected],
            ["previous evening boundary", "overnight item"],
        )

    def test_midday_window_includes_current_day_from_10_until_before_15(self):
        now = datetime(2026, 8, 15, 15, 0, tzinfo=VN_TZ)
        items = [
            {"title": "before morning boundary", "published_at": "2026-08-15 09:59"},
            {"title": "morning boundary", "published_at": "2026-08-15 10:00"},
            {"title": "midday item", "published_at": "2026-08-15 14:59"},
            {"title": "afternoon boundary", "published_at": "2026-08-15 15:00"},
        ]

        selected = filter_items_by_window(items, "midday", now=now)

        self.assertEqual(
            [item["title"] for item in selected],
            ["morning boundary", "midday item"],
        )

    def test_afternoon_window_includes_current_day_from_15_through_17(self):
        now = datetime(2026, 8, 15, 17, 0, tzinfo=VN_TZ)
        items = [
            {"title": "before afternoon boundary", "published_at": "2026-08-15 14:59"},
            {"title": "afternoon boundary", "published_at": "2026-08-15 15:00"},
            {"title": "late afternoon item", "published_at": "2026-08-15 16:59"},
            {"title": "evening boundary", "published_at": "2026-08-15 17:00"},
            {"title": "after evening boundary", "published_at": "2026-08-15 17:01"},
        ]

        selected = filter_items_by_window(items, "afternoon", now=now)

        self.assertEqual(
            [item["title"] for item in selected],
            ["afternoon boundary", "late afternoon item", "evening boundary"],
        )

    def test_evening_window_includes_current_day_from_17_through_22(self):
        now = datetime(2026, 8, 15, 22, 0, tzinfo=VN_TZ)
        items = [
            {"title": "before evening boundary", "published_at": "2026-08-15 16:59"},
            {"title": "evening boundary", "published_at": "2026-08-15 17:00"},
            {"title": "evening item", "published_at": "2026-08-15 21:59"},
            {"title": "night boundary", "published_at": "2026-08-15 22:00"},
            {"title": "after night boundary", "published_at": "2026-08-15 22:01"},
        ]

        selected = filter_items_by_window(items, "evening", now=now)

        self.assertEqual(
            [item["title"] for item in selected],
            ["evening boundary", "evening item", "night boundary"],
        )

    def test_auto_window_selects_morning_midday_afternoon_then_evening(self):
        self.assertEqual(
            resolve_window("auto", now=datetime(2026, 8, 15, 13, 29, tzinfo=VN_TZ)),
            "morning",
        )
        self.assertEqual(
            resolve_window("auto", now=datetime(2026, 8, 15, 15, 30, tzinfo=VN_TZ)),
            "midday",
        )
        self.assertEqual(
            resolve_window("auto", now=datetime(2026, 8, 15, 17, 0, tzinfo=VN_TZ)),
            "afternoon",
        )
        self.assertEqual(
            resolve_window("auto", now=datetime(2026, 8, 15, 22, 0, tzinfo=VN_TZ)),
            "evening",
        )


if __name__ == "__main__":
    unittest.main()
