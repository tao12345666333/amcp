#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "requests>=2.31.0",
#     "telegramify-markdown>=0.5.0",
# ]
# ///

"""
Telegram Bot Message Sender for AMCP.

Send or edit messages and photos via Telegram Bot API.
Uses telegramify_markdown for proper MarkdownV2 conversion.
"""

import argparse
import mimetypes
import os
import sys
import tempfile
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlparse

import requests

try:
    from telegramify_markdown import markdownify
except ImportError:
    print("Error: telegramify_markdown not installed. Run: pip install telegramify-markdown")
    sys.exit(1)


PHOTO_CAPTION_LIMIT = 1024
DOWNLOAD_CHUNK_SIZE = 64 * 1024
IMAGE_SUFFIX_BY_CONTENT_TYPE = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


def _unescape_newlines(text: str) -> str:
    """Convert escaped newline sequences to real newlines."""
    result = text.replace("\\n", "\n")
    result = result.replace("\\r\\n", "\r\n")
    result = result.replace("\\r", "\r")
    return result


def _to_markdownv2(text: str) -> str:
    """Convert user-friendly markdown text to Telegram MarkdownV2."""
    return markdownify(_unescape_newlines(text)).rstrip("\n")


def _is_url(value: str) -> bool:
    """Return whether value is an HTTP(S) URL."""
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _looks_like_file_id(value: str) -> bool:
    """Heuristically detect Telegram file_id values.

    Telegram file IDs are opaque strings. Avoid classifying local paths or URLs as file IDs;
    otherwise accept long slash-free values that commonly appear in Bot API responses.
    """
    return len(value) > 40 and "/" not in value and "\\" not in value and not _is_url(value)


def _guess_image_suffix(url: str, content_type: str | None) -> str:
    """Choose a useful file suffix for a downloaded image."""
    path_suffix = Path(urlparse(url).path).suffix.lower()
    if path_suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
        return ".jpg" if path_suffix == ".jpeg" else path_suffix

    media_type = (content_type or "").split(";", maxsplit=1)[0].strip().lower()
    if media_type in IMAGE_SUFFIX_BY_CONTENT_TYPE:
        return IMAGE_SUFFIX_BY_CONTENT_TYPE[media_type]

    guessed = mimetypes.guess_extension(media_type) if media_type else None
    if guessed in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
        return ".jpg" if guessed == ".jpeg" else guessed

    return ".jpg"


def _download_to_temp(url: str) -> str:
    """Download an image URL to a temporary file and return its path."""
    response = requests.get(url, stream=True, timeout=60)
    response.raise_for_status()

    suffix = _guess_image_suffix(url, response.headers.get("content-type"))
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
        for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
            if chunk:
                tmp_file.write(chunk)
        return tmp_file.name


def send_message(
    bot_token: str,
    chat_id: str,
    text: str,
    reply_to_message_id: int | None = None,
    mention_username: str | None = None,
) -> dict:
    """
    Send a message via Telegram Bot API.

    Args:
        bot_token: Telegram bot token
        chat_id: Target chat ID
        text: Message text (markdown supported, converted to MarkdownV2)
        reply_to_message_id: Optional message ID to reply to
        mention_username: Optional username to prefix with @ mention

    Returns:
        API response as dict
    """
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    if mention_username:
        text = f"@{mention_username} {text}"

    converted_text = _to_markdownv2(text)

    payload = {
        "chat_id": chat_id,
        "text": converted_text,
        "parse_mode": "MarkdownV2",
    }

    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id

    response = requests.post(url, json=payload, timeout=30)
    response.raise_for_status()

    return response.json()


def send_photo(
    bot_token: str,
    chat_id: str,
    photo: str,
    caption: str | None = None,
    reply_to_message_id: int | None = None,
    mention_username: str | None = None,
) -> dict:
    """
    Send a photo via Telegram Bot API.

    Args:
        bot_token: Telegram bot token
        chat_id: Target chat ID
        photo: Local file path, HTTP(S) URL, or Telegram file_id
        caption: Optional photo caption (markdown supported, converted to MarkdownV2)
        reply_to_message_id: Optional message ID to reply to
        mention_username: Optional username to prefix with @ mention

    Returns:
        API response as dict
    """
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    payload = {"chat_id": chat_id}

    if caption:
        if mention_username:
            caption = f"@{mention_username} {caption}"
        converted_caption = _to_markdownv2(caption)
        if len(converted_caption) > PHOTO_CAPTION_LIMIT:
            raise ValueError(f"Photo caption is too long ({len(converted_caption)} > {PHOTO_CAPTION_LIMIT})")
        payload["caption"] = converted_caption
        payload["parse_mode"] = "MarkdownV2"

    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id

    temp_path: str | None = None
    upload_path: Path | None = None
    try:
        photo_path = Path(photo).expanduser()
        if photo_path.is_file():
            upload_path = photo_path
        elif _is_url(photo):
            temp_path = _download_to_temp(photo)
            upload_path = Path(temp_path)
        elif _looks_like_file_id(photo):
            payload["photo"] = photo
            response = requests.post(url, json=payload, timeout=30)
            response.raise_for_status()
            return response.json()
        else:
            raise ValueError("Photo must be a local file path, HTTP(S) URL, or Telegram file_id")

        with upload_path.open("rb") as photo_file:
            files = {"photo": (upload_path.name, photo_file)}
            response = requests.post(url, data=payload, files=files, timeout=60)
            response.raise_for_status()
            return response.json()
    finally:
        if temp_path:
            with suppress(OSError):
                os.unlink(temp_path)


def edit_message(bot_token: str, chat_id: str, message_id: int, text: str) -> dict:
    """
    Edit an existing message via Telegram Bot API.

    Args:
        bot_token: Telegram bot token
        chat_id: Target chat ID
        message_id: ID of the message to edit
        text: New message text (markdown supported, converted to MarkdownV2)

    Returns:
        API response as dict
    """
    url = f"https://api.telegram.org/bot{bot_token}/editMessageText"

    converted_text = _to_markdownv2(text)

    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": converted_text,
        "parse_mode": "MarkdownV2",
    }

    response = requests.post(url, json=payload, timeout=30)
    response.raise_for_status()

    return response.json()


def main():
    parser = argparse.ArgumentParser(description="Send or edit Telegram messages/photos (auto-converts to MarkdownV2)")
    sub = parser.add_subparsers(dest="action", required=True)

    # --- send ---
    send_parser = sub.add_parser("send", help="Send a new message")
    send_parser.add_argument("--chat-id", "-c", required=True, help="Target chat ID")
    send_parser.add_argument("--message", "-m", required=True, help="Message text (markdown supported)")
    send_parser.add_argument("--token", "-t", help="Bot token (defaults to AMCP_TELEGRAM_BOT_TOKEN env)")
    send_parser.add_argument("--reply-to", "-r", type=int, help="Message ID to reply to")
    send_parser.add_argument(
        "--source-is-bot",
        action="store_true",
        help="Source message sender is a bot; disables reply and uses @username style",
    )
    send_parser.add_argument("--source-username", help="Username for @mention when --source-is-bot is set")

    # --- edit ---
    edit_parser = sub.add_parser("edit", help="Edit an existing message")
    edit_parser.add_argument("--chat-id", "-c", required=True, help="Target chat ID")
    edit_parser.add_argument("--message-id", "-i", type=int, required=True, help="ID of the message to edit")
    edit_parser.add_argument("--text", "-x", required=True, help="New message text (markdown supported)")
    edit_parser.add_argument("--token", "-t", help="Bot token (defaults to AMCP_TELEGRAM_BOT_TOKEN env)")

    # --- photo ---
    photo_parser = sub.add_parser("photo", help="Send a photo")
    photo_parser.add_argument("--chat-id", "-c", required=True, help="Target chat ID")
    photo_parser.add_argument(
        "--photo",
        "-p",
        required=True,
        help="Photo source: local file path, HTTP(S) URL, or Telegram file_id",
    )
    photo_parser.add_argument("--caption", "-m", help="Optional photo caption (markdown supported)")
    photo_parser.add_argument("--token", "-t", help="Bot token (defaults to AMCP_TELEGRAM_BOT_TOKEN env)")
    photo_parser.add_argument("--reply-to", "-r", type=int, help="Message ID to reply to")
    photo_parser.add_argument(
        "--source-is-bot",
        action="store_true",
        help="Source message sender is a bot; disables reply and uses @username style",
    )
    photo_parser.add_argument("--source-username", help="Username for @mention when --source-is-bot is set")

    args = parser.parse_args()

    bot_token = getattr(args, "token", None) or os.environ.get("AMCP_TELEGRAM_BOT_TOKEN")
    if not bot_token:
        print("Error: Bot token required. Set AMCP_TELEGRAM_BOT_TOKEN env var or use --token")
        sys.exit(1)

    try:
        if args.action == "send":
            reply_to = args.reply_to
            mention_username = None
            if args.source_is_bot:
                if not args.source_username:
                    print("Error: --source-username is required when --source-is-bot is set")
                    sys.exit(1)
                reply_to = None
                mention_username = args.source_username

            result = send_message(bot_token, args.chat_id, args.message, reply_to, mention_username)
            msg_id = result.get("result", {}).get("message_id", "?")
            print(f"Message sent (message_id={msg_id})")

        elif args.action == "edit":
            edit_message(bot_token, args.chat_id, args.message_id, args.text)
            print(f"Message {args.message_id} edited successfully")

        elif args.action == "photo":
            reply_to = args.reply_to
            mention_username = None
            if args.source_is_bot:
                if not args.source_username:
                    print("Error: --source-username is required when --source-is-bot is set")
                    sys.exit(1)
                reply_to = None
                mention_username = args.source_username

            result = send_photo(
                bot_token,
                args.chat_id,
                args.photo,
                args.caption,
                reply_to,
                mention_username,
            )
            msg_id = result.get("result", {}).get("message_id", "?")
            print(f"Photo sent (message_id={msg_id})")

    except requests.HTTPError as e:
        print(f"HTTP Error: {e}")
        if e.response is not None:
            print(f"Response: {e.response.text}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
