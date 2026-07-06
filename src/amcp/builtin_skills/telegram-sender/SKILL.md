---
name: telegram-sender
description: Send and edit Telegram messages, and send photos via Bot API. Use when AMCP needs to send text, reply to a specific message, edit an existing message, send an image, or push proactive notifications (cron results, heartbeat alerts, task status). Requires AMCP_TELEGRAM_BOT_TOKEN env var.
---

# Telegram Sender

Agent-facing guide for outbound Telegram communication.

Assumption: `AMCP_TELEGRAM_BOT_TOKEN` is already set in the environment.

## Required Inputs

- `chat_id` (required) — from inbound message metadata or config
- message content (required for send/edit)
- photo source (required for photo): local file path, HTTP(S) image URL, or Telegram `file_id`
- photo caption (optional, max 1024 characters after Telegram entity parsing)
- `reply_to_message_id` (optional, for threaded reply)
- `message_id` (required for edit)

## Execution Policy

1. If handling a Telegram message and `message_id` is known, prefer reply mode (`--reply-to`).
2. If source metadata says sender is a bot (`sender_is_bot=true`), do not use reply mode; use `--source-is-bot --source-username <USERNAME>` instead.
3. For long-running tasks: send an acknowledgment first, then edit it with the final result.
4. Use `photo` when the response depends on an image artifact or generated picture.
5. Prefer local file paths for newly generated images. Use a Telegram `file_id` only when reusing a previously uploaded file.
6. Keep content concise and action-oriented.
7. Use literal newlines in message text and captions.

## Active Response Policy

When this skill is in scope, prefer proactive and timely Telegram updates:

- Send immediate acknowledgment for newly assigned tasks
- Send progress updates for long-running operations using message edits
- Send completion notifications when work finishes
- Send failure notifications immediately with cause, impact, and next action

Recommended pattern:

1. Send a short acknowledgment reply
2. Continue processing
3. Edit the acknowledgment with final result (or send a new update if edit fails)

## Command Templates

Paths are relative to this skill directory.

```bash
# Send message
python ./scripts/telegram_send.py send \
  --chat-id <CHAT_ID> \
  --message "<TEXT>"

# Reply to a specific message
python ./scripts/telegram_send.py send \
  --chat-id <CHAT_ID> \
  --message "<TEXT>" \
  --reply-to <MESSAGE_ID>

# Bot-source: no direct reply, use @username style
python ./scripts/telegram_send.py send \
  --chat-id <CHAT_ID> \
  --message "<TEXT>" \
  --source-is-bot \
  --source-username <USERNAME>

# Edit existing message
python ./scripts/telegram_send.py edit \
  --chat-id <CHAT_ID> \
  --message-id <MESSAGE_ID> \
  --text "<TEXT>"

# Send photo from local path, URL, or Telegram file_id
python ./scripts/telegram_send.py photo \
  --chat-id <CHAT_ID> \
  --photo "<PATH_OR_URL_OR_FILE_ID>" \
  --caption "<OPTIONAL_CAPTION>"

# Reply with a photo
python ./scripts/telegram_send.py photo \
  --chat-id <CHAT_ID> \
  --photo "<PATH_OR_URL_OR_FILE_ID>" \
  --caption "<OPTIONAL_CAPTION>" \
  --reply-to <MESSAGE_ID>
```

For actions not covered by this script, use `curl` to call Telegram Bot API directly:
`https://api.telegram.org/bot$AMCP_TELEGRAM_BOT_TOKEN/<method>`

## Script Reference

### `telegram_send.py send`

- `--chat-id`, `-c`: required
- `--message`, `-m`: required
- `--reply-to`, `-r`: optional message ID
- `--token`, `-t`: optional (normally not needed)
- `--source-is-bot`: optional flag
- `--source-username`: required when `--source-is-bot` is set

### `telegram_send.py edit`

- `--chat-id`, `-c`: required
- `--message-id`, `-i`: required
- `--text`, `-x`: required
- `--token`, `-t`: optional (normally not needed)

### `telegram_send.py photo`

- `--chat-id`, `-c`: required
- `--photo`, `-p`: required; local file path, HTTP(S) URL, or Telegram `file_id`
- `--caption`, `-m`: optional caption; Markdown supported and converted to MarkdownV2
- `--reply-to`, `-r`: optional message ID
- `--token`, `-t`: optional (normally not needed)
- `--source-is-bot`: optional flag
- `--source-username`: required when `--source-is-bot` is set

Photo behavior:

- Local paths are uploaded with multipart/form-data.
- HTTP(S) URLs are downloaded to a temporary file and then uploaded, which avoids CDN
  content-type issues that can make direct Telegram URL sends fail.
- Telegram `file_id` values are sent directly to reuse an existing upload.
- Captions follow Telegram's `sendPhoto` limit: 0-1024 characters after entity parsing.

## Failure Handling

- On HTTP errors, inspect API response text and adjust identifiers/permissions.
- If edit fails (message not editable), fall back to a new send.
- If reply target is invalid, resend without `--reply-to`.
- If photo upload fails, verify the file exists, the URL is publicly fetchable from the
  current environment, or the `file_id` belongs to this bot.
- For task-level failures, notify the user with what failed, what completed, and next steps.
