#!/usr/bin/env python3
"""Test script to verify Telegram integration functionality."""

import sys
sys.path.insert(0, 'src')

from amcp.telegram import TelegramBot, TelegramClient, TelegramConfig
from amcp.telegram.auth import AuthMiddleware
from amcp.telegram.formatter import TelegramFormatter
from amcp.telegram.handlers import SessionManager, RateLimiter


def test_config():
    """Test Telegram configuration."""
    config = TelegramConfig()
    assert config.enabled is False
    assert config.bot_token is None
    assert config.allowed_users == []
    assert config.admin_users == []
    print("✓ TelegramConfig works")


def test_auth():
    """Test authentication middleware."""
    auth = AuthMiddleware(allowed_users={1, 2}, admin_users={2})
    assert auth.is_authorized(1)
    assert not auth.is_authorized(3)
    assert auth.is_admin(2)
    assert not auth.is_admin(1)
    print("✓ AuthMiddleware works")


def test_formatter():
    """Test message formatter."""
    formatter = TelegramFormatter(max_length=4096)
    
    # Test basic text
    chunks = formatter.format_response("Hello world!")
    assert chunks == ["Hello world!"]
    
    # Test markdown escaping
    chunks = formatter.format_response("Hello *world*!")
    assert chunks == ["Hello \\*world\\*\\!"]
    
    # Test code blocks
    chunks = formatter.format_response("```python\nprint('hi')\n```")
    assert chunks[0].startswith("```python")
    assert chunks[0].endswith("```")
    
    # Test long text splitting
    formatter = TelegramFormatter(max_length=10)
    chunks = formatter.format_response("1234567890 123")
    assert all(len(chunk) <= 10 for chunk in chunks)
    
    print("✓ TelegramFormatter works")


def test_session_manager():
    """Test session management."""
    def fake_agent_factory(session_id: str):
        return f"agent-{session_id}"
    
    manager = SessionManager(agent_factory=fake_agent_factory, session_timeout=60)
    session = manager.get_or_create_session(123)
    assert session.session_id.startswith("telegram-123-")
    
    session2 = manager.create_session(123)
    assert manager.switch_session(123, session2.session_id)
    assert manager.get_current_session_id(123) == session2.session_id
    
    print("✓ SessionManager works")


def test_rate_limiter():
    """Test rate limiting."""
    limiter = RateLimiter(limit=5, window_seconds=60)
    
    # Should allow first 5 requests
    for i in range(5):
        assert limiter.allow(123) is True
    
    # Should deny 6th request
    assert limiter.allow(123) is False
    
    print("✓ RateLimiter works")


def test_bot_creation():
    """Test Telegram bot creation (without starting)."""
    try:
        bot = TelegramBot(
            token="test_token",
            allowed_users={1, 2},
            admin_users={2},
            config=TelegramConfig(enabled=True)
        )
        assert bot.config.enabled is True
        assert bot.config.bot_token == "test_token"
        print("✓ TelegramBot creation works")
    except RuntimeError as e:
        if "python-telegram-bot is required" in str(e):
            print("✓ TelegramBot correctly detects missing dependency")
        else:
            raise


def main():
    """Run all tests."""
    print("Testing Telegram integration...")
    print()
    
    test_config()
    test_auth()
    test_formatter()
    test_session_manager()
    test_rate_limiter()
    test_bot_creation()
    
    print()
    print("🎉 All Telegram integration tests passed!")
    print()
    print("To use Telegram integration:")
    print("1. Install with: pip install -e .[telegram]")
    print("2. Set up bot token: amcp telegram setup")
    print("3. Start bot: amcp telegram start")
    print("4. Or start with server: amcp server --telegram")


if __name__ == "__main__":
    main()