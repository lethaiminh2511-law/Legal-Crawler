import os
import json
import requests
from pathlib import Path
from typing import List, Dict

from dotenv import load_dotenv
load_dotenv()

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "1141777845693322")
TO_PHONE = os.getenv("WHATSAPP_TO_PHONE", "84914230081")

GRAPH_API_VERSION = "v25.0"


def send_whatsapp_text(message: str) -> dict:
    """
    Gửi text message qua WhatsApp Cloud API.
    Lưu ý: text message chỉ gửi được nếu số nhận đang trong 24h customer service window.
    Nếu gửi chủ động lần đầu, cần dùng template đã được approve.
    """

    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{PHONE_NUMBER_ID}/messages"

    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": TO_PHONE,
        "type": "text",
        "text": {
            "preview_url": True,
            "body": message,
        },
    }

    response = requests.post(url, headers=headers, json=payload, timeout=30)

    try:
        data = response.json()
    except Exception:
        data = {"raw_response": response.text}

    if not response.ok:
        raise RuntimeError(f"Failed to send WhatsApp message: {response.status_code} - {data}")

    return data


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
            f"{'─' * 20}\n"
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