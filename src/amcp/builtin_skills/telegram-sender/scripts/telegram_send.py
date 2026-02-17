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

Send or edit messages via Telegram Bot API.
Uses telegramify_markdown for proper MarkdownV2 conversion.
"""

import argparse
import os
import sys

import requests

try:
    from telegramify_markdown import markdownify
except ImportError:
    print("Error: telegramify_markdown not installed. Run: pip install telegramify-markdown")
    sys.exit(1)


def _unescape_newlines(text: str) -> str:
    """Convert escaped newline sequences to real newlines."""
    result = text.replace("\\n", "\n")
    result = result.replace("\\r\\n", "\r\n")
    result = result.replace("\\r", "\r")
    return result


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

    text = _unescape_newlines(text)
    if mention_username:
        text = f"@{mention_username} {text}"

    converted_text = markdownify(text).rstrip("\n")

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

    text = _unescape_newlines(text)
    converted_text = markdownify(text).rstrip("\n")

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
    parser = argparse.ArgumentParser(
        description="Send or edit messages via Telegram Bot API (auto-converts to MarkdownV2)"
    )
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
