from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass, field


@dataclass
class TelegramNotificationsConfig:
    ci_failures: bool = True
    pr_reviews: bool = True
    task_completions: bool = True
    error_alerts: bool = True


@dataclass
class TelegramConfig:
    enabled: bool = False
    bot_token: str | None = None
    allowed_users: list[int] = field(default_factory=list)
    admin_users: list[int] = field(default_factory=list)
    webhook_mode: bool = False
    webhook_url: str | None = None
    max_message_length: int = 4096
    rate_limit_messages: int = 20
    session_timeout: int = 3600
    notifications: TelegramNotificationsConfig = field(default_factory=TelegramNotificationsConfig)


def _coerce_user_ids(values: Iterable[object]) -> list[int]:
    user_ids: list[int] = []
    for value in values:
        if value is None:
            continue
        try:
            user_ids.append(int(str(value).strip()))
        except (TypeError, ValueError):
            continue
    return user_ids


def parse_user_ids(value: object | None) -> list[int]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",")]
        return _coerce_user_ids([part for part in parts if part])
    if isinstance(value, Iterable):
        return _coerce_user_ids(value)
    return []


def apply_env_overrides(cfg: TelegramConfig | None) -> TelegramConfig | None:
    token = os.environ.get("AMCP_TELEGRAM_BOT_TOKEN")
    allowed = parse_user_ids(os.environ.get("AMCP_TELEGRAM_ALLOWED_USERS"))
    admin = parse_user_ids(os.environ.get("AMCP_TELEGRAM_ADMIN_USERS"))

    if cfg is None and (token or allowed or admin):
        cfg = TelegramConfig(enabled=True)

    if cfg is None:
        return None

    if token:
        cfg.bot_token = token
        cfg.enabled = True
    if allowed:
        cfg.allowed_users = allowed
    if admin:
        cfg.admin_users = admin

    return cfg
