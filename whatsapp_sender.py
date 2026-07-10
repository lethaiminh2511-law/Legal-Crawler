import os
import json
import requests
import argparse
from datetime import datetime, time
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
load_dotenv()

WHATSAPP_API_KEY = os.getenv("WHATSAPP_API_KEY")
CHANNEL_ID = "120363409024011943@newsletter"
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

WINDOWS = {
    "morning": (time(0, 0), time(10, 0)),
    "afternoon": (time(10, 0), time(17, 0)),
}


def send_whatsapp_text(message: str) -> dict:

    url = "http://localhost:3000/api/sendText"
    headers = {
        "X-Api-Key": WHATSAPP_API_KEY,
        "Content-Type": "application/json",
    }
    data = {
        "session": "default",
        "chatId": CHANNEL_ID,
        "text": message
    }

    response = requests.post(url, json=data, headers=headers)
    print(response.json())


def parse_published_at(raw: str) -> Optional[datetime]:
    raw = (raw or "").strip()
    if not raw:
        return None

    candidates = [
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d",
        "%d/%m/%Y",
    ]

    if raw.endswith("Z"):
        raw = raw[:-1] + "+0000"

    for fmt in candidates:
        try:
            parsed = datetime.strptime(raw, fmt)
        except ValueError:
            continue

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=VN_TZ)
        return parsed.astimezone(VN_TZ)

    return None


def resolve_window(window: str, now: Optional[datetime] = None) -> str:
    if window != "auto":
        return window

    now = now or datetime.now(VN_TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=VN_TZ)
    now = now.astimezone(VN_TZ)

    return "morning" if now.time() < time(13, 30) else "afternoon"


def get_article_window(window: str, today: datetime) -> Tuple[datetime, datetime]:
    start_time, end_time = WINDOWS[window]
    target_date = today.astimezone(VN_TZ).date()
    return (
        datetime.combine(target_date, start_time, tzinfo=VN_TZ),
        datetime.combine(target_date, end_time, tzinfo=VN_TZ),
    )


def is_in_window(published_at: Optional[datetime], start_at: datetime, end_at: datetime) -> bool:
    if not published_at:
        return True

    published_at = published_at.astimezone(VN_TZ)
    if end_at.time() == time(17, 0):
        return start_at <= published_at <= end_at
    return start_at <= published_at < end_at


def filter_items_by_window(items: List[Dict], window: str, now: Optional[datetime] = None) -> List[Dict]:
    now = now or datetime.now(VN_TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=VN_TZ)
    now = now.astimezone(VN_TZ)

    resolved_window = resolve_window(window, now)
    start_at, end_at = get_article_window(resolved_window, now)

    return [
        item
        for item in items
        if is_in_window(parse_published_at(item.get("published_at", "")), start_at, end_at)
    ]


def format_crawled_items(items: List[Dict]) -> str:
    """
    Format danh sách bài đã crawl thành message ngắn để gửi WhatsApp.
    """

    if not items:
        return "Không có thông tin mới được crawl."

    lines = ["Legal Crawler - Có thông tin mới:\n"]

    for idx, item in enumerate(items, start=1):
        title = (item.get("title", "") or "").strip()
        source = (item.get("source", "") or "").strip()
        published_at = (item.get("published_at", "") or "").strip()
        summary = (item.get("summary_raw", "") or "").strip()
        url = (item.get("url", "") or "").strip()

        lines.append(
            f"📰 *{title}*\n\n"
            f"🏛️ *Nguồn:* {source}\n"
            f"📅 *Thời gian:* {published_at}\n\n"
            f"📝 *Tóm tắt*\n"
            f"{summary}\n\n"
            f"🔗 *Chi tiết:*\n{url}\n"
            f"{'─' * 10}\n"
        )

    return "\n".join(lines)


def send_crawled_info_to_whatsapp(items: List[Dict]) -> dict:
    message = format_crawled_items(items)
    return send_whatsapp_text(message)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Send crawled legal articles to WhatsApp for the configured cron window."
    )
    parser.add_argument(
        "--window",
        choices=["auto", "morning", "afternoon"],
        default="auto",
        help=(
            "morning: today before 10:00; afternoon: today from 10:00 through 17:00. "
            "auto picks morning before 13:30, otherwise afternoon."
        ),
    )
    args = parser.parse_args()

    crawled_items = []
    crawler_path = Path(".")
    for file in crawler_path.iterdir():

        if file.suffix != ".json":
            continue

        with open(file, encoding="utf-8") as f:
            crawled_data = json.load(f)

        crawled_items.extend(crawled_data)

    selected_window = resolve_window(args.window)
    crawled_items = filter_items_by_window(crawled_items, selected_window)
    print(f"Selected {len(crawled_items)} item(s) for {selected_window} WhatsApp window.")

    result = send_crawled_info_to_whatsapp(crawled_items)
    print(json.dumps(result, ensure_ascii=False, indent=2))
