"""Assertion evaluation: Phase 1 load / resilience checks from scenario YAML."""

from __future__ import annotations

import logging
from typing import Any, Mapping, MutableMapping

logger = logging.getLogger(__name__)


def _check_threshold(
    name: str,
    actual: float,
    op: str,
    limit: float,
    *,
    checks: list[dict[str, Any]],
) -> None:
    """Append one check result; op is 'min' (actual must be >= limit) or 'max'."""
    if op == "min":
        passed = actual >= limit
        detail = f"{actual} >= {limit}"
    elif op == "max":
        passed = actual <= limit
        detail = f"{actual} <= {limit}"
    else:
        passed = False
        detail = f"unknown op {op!r}"
    checks.append(
        {
            "name": name,
            "passed": passed,
            "detail": detail,
            "actual": actual,
            "limit": limit,
            "op": op,
        }
    )


def evaluate(observations: MutableMapping[str, Any], scenario: Mapping[str, Any]) -> None:
    """Run assertions from ``scenario['assertions']['load']`` against workload metrics.

    Mutates ``observations`` with::

        observations["assertion_results"] = {
            "overall_passed": bool,
            "checks": [...],
        }
    """
    logger.info("assertions.evaluate enter")
    raw_assert = scenario.get("assertions")
    load_rules: Mapping[str, Any] | None = None
    if isinstance(raw_assert, Mapping):
        lr = raw_assert.get("load")
        if isinstance(lr, Mapping):
            load_rules = lr

    checks: list[dict[str, Any]] = []
    wl = observations.get("workload")
    if not isinstance(wl, Mapping):
        wl = {}

    if load_rules:
        if "min_requests_total" in load_rules:
            _check_threshold(
                "load.min_requests_total",
                float(wl.get("requests_total", 0)),
                "min",
                float(load_rules["min_requests_total"]),
                checks=checks,
            )
        if "min_success_rate_pct" in load_rules:
            _check_threshold(
                "load.min_success_rate_pct",
                float(wl.get("success_rate_pct", 0.0)),
                "min",
                float(load_rules["min_success_rate_pct"]),
                checks=checks,
            )
        if "max_failed_requests" in load_rules:
            _check_threshold(
                "load.max_failed_requests",
                float(wl.get("requests_failed", 0)),
                "max",
                float(load_rules["max_failed_requests"]),
                checks=checks,
            )
        if "max_latency_mean_ms" in load_rules:
            _check_threshold(
                "load.max_latency_mean_ms",
                float(wl.get("latency_mean_ms", 0.0)),
                "max",
                float(load_rules["max_latency_mean_ms"]),
                checks=checks,
            )

    overall = all(c.get("passed", False) for c in checks if not c.get("skipped"))
    observations["assertion_results"] = {
        "overall_passed": overall if checks else True,
        "checks": checks,
    }
    logger.info(
        "assertions.evaluate exit overall_passed=%s checks=%d",
        observations["assertion_results"]["overall_passed"],
        len(checks),
    )
