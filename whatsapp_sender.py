import os
import json
import requests
from pathlib import Path
from typing import List, Dict

from dotenv import load_dotenv
load_dotenv()

WHATSAPP_API_KEY = os.getenv("WHATSAPP_API_KEY")
CHANNEL_ID = "120363409024011943@newsletter"

GRAPH_API_VERSION = "v25.0"


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


def format_crawled_items(items: List[Dict]) -> str:
    """
    Format danh sách bài đã crawl thành message ngắn để gửi WhatsApp.
    """

    if not items:
        return "Không có thông tin mới được crawl."

    lines = ["Legal Crawler - Có thông tin mới:\n"]

    for idx, item in enumerate(items, start=1):
        title = item.get("title", "").strip()
        source = item.get("source", "").strip()
        published_at = item.get("published_at", "").strip()
        summary = item.get("summary_raw", "").strip()
        url = item.get("url", "").strip()

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
    crawled_items = []
    crawler_path = Path(".")
    for file in crawler_path.iterdir():

        if file.suffix != ".json":
            continue

        with open(file, encoding="utf-8") as f:
            crawled_data = json.load(f)

        crawled_items.extend(crawled_data)

    result = send_crawled_info_to_whatsapp(crawled_items)
    print(json.dumps(result, ensure_ascii=False, indent=2))