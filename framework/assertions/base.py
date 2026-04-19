"""Stub assertion evaluation: logs only."""

from __future__ import annotations

import logging
from typing import Any, Mapping

logger = logging.getLogger(__name__)


def evaluate(observations: Mapping[str, Any], scenario: Mapping[str, Any]) -> None:
    logger.info("assertions.evaluate enter")
    logger.debug(
        "assertions.evaluate (stub: would run resilience/security checks; observations keys=%s)",
        list(observations.keys()),
    )
    logger.info("assertions.evaluate exit")
