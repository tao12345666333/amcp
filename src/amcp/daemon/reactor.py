"""EventReactor — react to external events such as GitHub webhooks."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..event_bus import Event, EventType, get_event_bus
from .config import ReactorConfig

logger = logging.getLogger(__name__)


@dataclass
class ReactionRule:
    """A rule that maps an event pattern to an agent command."""

    name: str
    event_type: str  # e.g. "github.push", "github.pr"
    filter_fn: Callable[[dict], bool] | None = None
    command_template: str = ""
    skill: str | None = None
    tags: list[str] = field(default_factory=list)


class EventReactor:
    """React to external events (e.g. GitHub webhooks) by scheduling agent tasks.

    When the reactor is enabled it starts a lightweight HTTP listener that
    accepts webhook payloads and converts them into agent commands.  Rules
    are matched against incoming events and dispatched to the scheduler.
    """

    def __init__(
        self,
        config: ReactorConfig | None = None,
        *,
        schedule_fn: Callable[[str, str | None], Any] | None = None,
    ):
        self.config = config or ReactorConfig()
        self._schedule_fn = schedule_fn  # callback: (command, skill) -> None
        self._rules: dict[str, list[ReactionRule]] = {}
        self._running = False
        self._server: Any = None  # aiohttp or uvicorn server

        # Register built-in rules
        self._register_defaults()

    # ------------------------------------------------------------------
    # Rule management
    # ------------------------------------------------------------------

    def add_rule(self, rule: ReactionRule) -> None:
        self._rules.setdefault(rule.event_type, []).append(rule)

    def _register_defaults(self) -> None:
        """Register default reaction rules for GitHub events."""
        self.add_rule(
            ReactionRule(
                name="ci-on-push-main",
                event_type="github.push",
                filter_fn=lambda p: p.get("ref", "").endswith("/main"),
                command_template=(
                    "CI was triggered on the main branch. "
                    "Monitor the run and report any failures."
                ),
            )
        )

        self.add_rule(
            ReactionRule(
                name="review-new-pr",
                event_type="github.pull_request",
                filter_fn=lambda p: p.get("action") == "opened",
                command_template=(
                    "A new PR #{number} was opened: {title}. "
                    "Review it using the gh-code-review skill."
                ),
                skill="gh-code-review",
            )
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if not self.config.enabled:
            logger.info("EventReactor disabled")
            return
        self._running = True
        asyncio.create_task(self._run_http_server())
        logger.info("EventReactor started on port %d", self.config.listen_port)

    async def stop(self) -> None:
        self._running = False
        if self._server:
            self._server.close()
            with contextlib.suppress(Exception):
                await self._server.wait_closed()
        logger.info("EventReactor stopped")

    # ------------------------------------------------------------------
    # HTTP server (minimal, using built-in asyncio)
    # ------------------------------------------------------------------

    async def _run_http_server(self) -> None:
        """Start a minimal asyncio-based HTTP server to receive webhooks."""
        try:
            server = await asyncio.start_server(
                self._handle_connection,
                "0.0.0.0",
                self.config.listen_port,
            )
            self._server = server
            async with server:
                await server.serve_forever()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Webhook HTTP server failed")

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a raw TCP connection (minimal HTTP parsing)."""
        try:
            # Read HTTP request
            request_line = await asyncio.wait_for(reader.readline(), timeout=10)
            if not request_line:
                writer.close()
                return

            # Read headers
            headers: dict[str, str] = {}
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=10)
                if line in (b"\r\n", b"\n", b""):
                    break
                if b":" in line:
                    key, val = line.decode().split(":", 1)
                    headers[key.strip().lower()] = val.strip()

            # Read body
            content_length = int(headers.get("content-length", "0"))
            body = b""
            if content_length > 0:
                body = await asyncio.wait_for(reader.readexactly(content_length), timeout=30)

            # Parse request
            parts = request_line.decode().split()
            method = parts[0] if parts else ""
            path = parts[1] if len(parts) > 1 else "/"

            if method == "POST" and path.startswith("/webhook"):
                await self._process_webhook(headers, body)
                response = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK"
            elif method == "GET" and path == "/health":
                response = b'HTTP/1.1 200 OK\r\nContent-Length: 15\r\n\r\n{"status":"ok"}'
            else:
                response = b"HTTP/1.1 404 Not Found\r\nContent-Length: 9\r\n\r\nNot Found"

            writer.write(response)
            await writer.drain()
        except Exception:
            logger.debug("Error handling webhook connection", exc_info=True)
        finally:
            writer.close()

    # ------------------------------------------------------------------
    # Webhook processing
    # ------------------------------------------------------------------

    async def _process_webhook(self, headers: dict[str, str], body: bytes) -> None:
        """Process a GitHub webhook payload."""
        import json

        # Verify signature if secret is configured
        if self.config.github_webhook_secret:
            sig = headers.get("x-hub-signature-256", "")
            if not self._verify_signature(body, sig):
                logger.warning("Invalid webhook signature — ignoring")
                return

        try:
            payload = json.loads(body)
        except Exception:
            logger.warning("Invalid JSON in webhook payload")
            return

        event_type = headers.get("x-github-event", "unknown")
        github_event = f"github.{event_type}"

        logger.info("Received webhook event: %s", github_event)

        bus = get_event_bus()
        await bus.emit(
            Event(
                type=EventType.WEBHOOK_RECEIVED,
                source="reactor",
                data={"event_type": github_event, "payload_keys": list(payload.keys())},
            )
        )

        # Match rules
        rules = self._rules.get(github_event, [])
        for rule in rules:
            if rule.filter_fn and not rule.filter_fn(payload):
                continue

            # Format command template
            command = rule.command_template.format_map(_SafeDict(payload))
            logger.info("Rule %s matched — scheduling: %s", rule.name, command[:100])

            if self._schedule_fn:
                try:
                    await self._schedule_fn(command, rule.skill)
                except Exception:
                    logger.exception("Failed to schedule command for rule %s", rule.name)

    def _verify_signature(self, body: bytes, signature: str) -> bool:
        """Verify GitHub webhook HMAC-SHA256 signature."""
        if not signature.startswith("sha256="):
            return False
        expected = hmac.new(
            self.config.github_webhook_secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(f"sha256={expected}", signature)


class _SafeDict(dict):
    """Dict subclass that returns '{key}' for missing keys in format_map."""

    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"
