"""Central logging setup: logs go to stderr; CLI prints summaries on stdout."""

from __future__ import annotations

import logging
import sys
from typing import Optional


def setup_logging(level: int = logging.INFO, fmt: Optional[str] = None) -> None:
    """Configure the root logger once: stderr stream, consistent format."""
    if fmt is None:
        fmt = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(fmt))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
