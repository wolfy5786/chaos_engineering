"""Stub traffic monitor: logs only."""

from __future__ import annotations

import logging
from typing import Any, Mapping

logger = logging.getLogger(__name__)


def start(scenario: Mapping[str, Any]) -> None:
    logger.info("traffic_monitor.start enter")
    logger.debug("traffic_monitor.start (stub: would capture inter-service traffic)")
    logger.info("traffic_monitor.start exit")


def stop(scenario: Mapping[str, Any]) -> None:
    logger.info("traffic_monitor.stop enter")
    logger.debug("traffic_monitor.stop (stub: would finalize capture buffers)")
    logger.info("traffic_monitor.stop exit")
