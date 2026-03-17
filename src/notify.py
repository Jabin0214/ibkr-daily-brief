"""Telegram notification utilities."""

from __future__ import annotations

import os
import time

import requests

TELEGRAM_MESSAGE_LIMIT = 4096


def send_telegram(message: str) -> bool:
    """Send a Telegram message with retries and auto-splitting."""
    print("[Telegram] Preparing message delivery...")

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        print("[Telegram] Missing bot token or chat id.")
        return False

    chunks = _split_message(message, TELEGRAM_MESSAGE_LIMIT)
    endpoint = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    for index, chunk in enumerate(chunks, start=1):
        sent = False
        for attempt in range(3):
            try:
                response = requests.post(
                    endpoint,
                    json={
                        "chat_id": chat_id,
                        "text": chunk,
                        "disable_web_page_preview": True,
                    },
                    timeout=30,
                )
                response.raise_for_status()
                payload = response.json()
                if payload.get("ok"):
                    print(f"[Telegram] Sent chunk {index}/{len(chunks)}.")
                    sent = True
                    break
            except Exception as exc:
                print(f"[Telegram] Send failed on attempt {attempt + 1}/3: {exc}")
                time.sleep(2)

        if not sent:
            print(f"[Telegram] Failed to send chunk {index}/{len(chunks)}.")
            return False

    return True


def _split_message(message: str, limit: int) -> list[str]:
    """Split long Telegram messages into safe chunks."""
    if len(message) <= limit:
        return [message]

    chunks: list[str] = []
    current = ""
    paragraphs = message.split("\n\n")

    for paragraph in paragraphs:
        paragraph_with_spacing = paragraph if not current else f"\n\n{paragraph}"
        if len(current) + len(paragraph_with_spacing) <= limit:
            current += paragraph_with_spacing
            continue

        if current:
            chunks.append(current)
            current = ""

        if len(paragraph) <= limit:
            current = paragraph
            continue

        for line in paragraph.splitlines(keepends=True):
            if len(current) + len(line) <= limit:
                current += line
                continue

            if current:
                chunks.append(current)
                current = ""

            while len(line) > limit:
                chunks.append(line[:limit])
                line = line[limit:]
            current = line

    if current:
        chunks.append(current)

    return chunks or [message[:limit]]
