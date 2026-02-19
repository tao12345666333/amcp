from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass, field

VALID_DM_POLICIES = {"allowlist", "pairing", "open", "disabled"}
VALID_GROUP_POLICIES = {"mention", "open", "allowlist", "disabled"}


@dataclass
class TelegramNotificationsConfig:
    ci_failures: bool = True
    pr_reviews: bool = True
    task_completions: bool = True
    error_alerts: bool = True


@dataclass
class TelegramPairingConfig:
    enabled: bool = True
    code_ttl_seconds: int = 1800
    max_pending: int = 200


@dataclass
class TelegramTopicConfig:
    enabled: bool = True
    group_policy: str | None = None
    require_mention: bool | None = None
    allow_users: list[int] = field(default_factory=list)


@dataclass
class TelegramGroupConfig:
    enabled: bool = True
    group_policy: str | None = None
    require_mention: bool | None = None
    allow_users: list[int] = field(default_factory=list)
    topics: dict[str, TelegramTopicConfig] = field(default_factory=dict)


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
    dm_policy: str = "allowlist"
    group_policy: str = "mention"
    group_allow_users: list[int] = field(default_factory=list)
    typing_indicator: bool = True
    typing_interval_seconds: int = 4
    max_queue_size: int = 20
    pairing: TelegramPairingConfig = field(default_factory=TelegramPairingConfig)
    groups: dict[str, TelegramGroupConfig] = field(default_factory=dict)
    notifications: TelegramNotificationsConfig = field(default_factory=TelegramNotificationsConfig)
    assistant_mode: bool = False


def normalize_dm_policy(value: str | None) -> str:
    if not value:
        return "allowlist"
    lowered = value.strip().lower()
    if lowered in VALID_DM_POLICIES:
        return lowered
    return "allowlist"


def normalize_group_policy(value: str | None) -> str:
    if not value:
        return "mention"
    lowered = value.strip().lower()
    if lowered in VALID_GROUP_POLICIES:
        return lowered
    return "mention"


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
