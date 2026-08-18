"""Shared filesystem layout constants.

Single source of truth for on-disk directory names so the whole codebase
moves together when the layout changes (e.g. the amcp -> ankaloop rename).

ANKA_CONFIG_DIR_NAME overrides the config directory name (default
"ankaloop"). Set it to the legacy value ("amcp") to keep old deployments
working.
"""

from __future__ import annotations

import os

CONFIG_DIR_NAME = os.environ.get("ANKA_CONFIG_DIR_NAME", "ankaloop")
PROJECT_DIR_NAME = ".ankaloop"
