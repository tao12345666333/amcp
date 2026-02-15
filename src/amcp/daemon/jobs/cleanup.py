"""Cleanup job — clean up old sessions and compact memory."""

from __future__ import annotations

import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def cleanup_old_sessions(max_age_days: int = 30) -> int:
    """Delete session files older than *max_age_days*.

    Returns:
        Number of session files deleted.
    """
    sessions_dir = Path.home() / ".config" / "amcp" / "sessions"
    if not sessions_dir.exists():
        return 0

    cutoff = time.time() - (max_age_days * 86400)
    deleted = 0

    for session_file in sessions_dir.glob("*.json"):
        try:
            if session_file.stat().st_mtime < cutoff:
                session_file.unlink()
                deleted += 1
        except Exception:
            logger.debug("Could not delete session file %s", session_file)

    if deleted:
        logger.info("Cleaned up %d old session files", deleted)
    return deleted


def cleanup_daemon_logs(max_size_mb: int = 50) -> bool:
    """Truncate daemon log if it exceeds *max_size_mb*.

    Returns:
        True if the log was truncated.
    """
    log_file = Path.home() / ".config" / "amcp" / "logs" / "daemon.log"
    if not log_file.exists():
        return False

    size_mb = log_file.stat().st_size / (1024 * 1024)
    if size_mb <= max_size_mb:
        return False

    # Keep the last 10 000 lines
    try:
        lines = log_file.read_text().splitlines()
        keep = lines[-10000:]
        log_file.write_text("\n".join(keep) + "\n")
        logger.info("Truncated daemon log from %.1f MB", size_mb)
        return True
    except Exception:
        logger.debug("Could not truncate daemon log")
        return False
