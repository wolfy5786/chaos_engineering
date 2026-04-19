"""Stub fault injector: logs only."""

from __future__ import annotations

import logging
from typing import Any, Mapping

logger = logging.getLogger(__name__)


def baseline(scenario: Mapping[str, Any]) -> None:
    logger.info("fault_injector.baseline enter")
    logger.debug("fault_injector.baseline (stub: would establish no-fault baseline)")
    logger.info("fault_injector.baseline exit")


def inject(scenario: Mapping[str, Any]) -> None:
    logger.info("fault_injector.inject enter")
    logger.debug("fault_injector.inject (stub: would apply faults)")
    logger.info("fault_injector.inject exit")


def recover(scenario: Mapping[str, Any]) -> None:
    logger.info("fault_injector.recover enter")
    logger.debug("fault_injector.recover (stub: would remove faults)")
    logger.info("fault_injector.recover exit")
