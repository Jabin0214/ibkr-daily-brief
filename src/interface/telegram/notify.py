"""Telegram notification utilities."""

from __future__ import annotations

import os
import time
from pathlib import Path

from src.core.providers.networking import DEFAULT_TIMEOUT, get_requests_session

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
    session = get_requests_session()

    for index, chunk in enumerate(chunks, start=1):
        sent = False
        for attempt in range(3):
            try:
                response = session.post(
                    endpoint,
                    json={
                        "chat_id": chat_id,
                        "text": chunk,
                        "disable_web_page_preview": True,
                    },
                    timeout=DEFAULT_TIMEOUT,
                )
                response.raise_for_status()
                payload = response.json()
                if payload.get("ok"):
                    print(f"[Telegram] Sent chunk {index}/{len(chunks)}.")
                    sent = True
                    break
                raise ValueError(f"Telegram API returned ok=false: {payload}")
            except Exception as exc:
                print(f"[Telegram] Send failed on attempt {attempt + 1}/3: {exc}")
                time.sleep(2)

        if not sent:
            print(f"[Telegram] Failed to send chunk {index}/{len(chunks)}.")
            return False

    return True


def send_telegram_document(file_path: Path, caption: str = "") -> bool:
    """Send a document attachment to Telegram with retries."""
    print(f"[Telegram] Preparing document delivery: {file_path.name}")

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        print("[Telegram] Missing bot token or chat id.")
        return False

    endpoint = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    session = get_requests_session()

    for attempt in range(3):
        try:
            with file_path.open("rb") as report_file:
                response = session.post(
                    endpoint,
                    data={
                        "chat_id": chat_id,
                        "caption": caption[:1024],
                        "disable_content_type_detection": False,
                    },
                    files={"document": (file_path.name, report_file, "text/html")},
                    timeout=DEFAULT_TIMEOUT,
                )
            response.raise_for_status()
            payload = response.json()
            if payload.get("ok"):
                print(f"[Telegram] Document sent: {file_path.name}")
                return True
            raise ValueError(f"Telegram API returned ok=false: {payload}")
        except Exception as exc:
            print(f"[Telegram] Document send failed on attempt {attempt + 1}/3: {exc}")
            time.sleep(2)

    print(f"[Telegram] Failed to send document: {file_path.name}")
    return False


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
