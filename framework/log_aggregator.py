"""Stub log aggregator: logs only."""

from __future__ import annotations

import logging
from typing import Any, Mapping

logger = logging.getLogger(__name__)


def start(scenario: Mapping[str, Any]) -> None:
    logger.info("log_aggregator.start enter")
    logger.debug("log_aggregator.start (stub: would tail/stream target logs)")
    logger.info("log_aggregator.start exit")


def stop(scenario: Mapping[str, Any]) -> None:
    logger.info("log_aggregator.stop enter")
    logger.debug("log_aggregator.stop (stub: would flush and close log streams)")
    logger.info("log_aggregator.stop exit")
