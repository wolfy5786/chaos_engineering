"""Tests for framework.assertions load thresholds."""

from __future__ import annotations

from framework.assertions.base import evaluate


def test_load_assertions_pass() -> None:
    obs: dict = {
        "workload": {
            "requests_total": 100,
            "requests_success": 90,
            "requests_failed": 10,
            "success_rate_pct": 90.0,
            "latency_mean_ms": 12.0,
        }
    }
    scenario = {
        "assertions": {
            "load": {
                "min_requests_total": 50,
                "min_success_rate_pct": 80.0,
                "max_failed_requests": 20,
                "max_latency_mean_ms": 100.0,
            }
        }
    }
    evaluate(obs, scenario)
    assert obs["assertion_results"]["overall_passed"] is True
    assert len(obs["assertion_results"]["checks"]) == 4


def test_load_assertions_fail_on_success_rate() -> None:
    obs: dict = {
        "workload": {
            "requests_total": 100,
            "requests_success": 50,
            "requests_failed": 50,
            "success_rate_pct": 50.0,
            "latency_mean_ms": 5.0,
        }
    }
    scenario = {"assertions": {"load": {"min_success_rate_pct": 90.0}}}
    evaluate(obs, scenario)
    assert obs["assertion_results"]["overall_passed"] is False


def test_no_assertions_is_pass() -> None:
    obs: dict = {"workload": {"requests_total": 0}}
    evaluate(obs, {})
    assert obs["assertion_results"]["overall_passed"] is True
    assert obs["assertion_results"]["checks"] == []
