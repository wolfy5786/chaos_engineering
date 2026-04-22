"""Tests for workload metrics deltas, burst summary, and effective RPS."""

from __future__ import annotations

from framework import workload_generator as wg


def test_diff_workload_metrics_basic() -> None:
    early = {
        "requests_total": 10,
        "requests_success": 8,
        "requests_failed": 2,
        "latency_sum_ms": 100.0,
        "latency_min_ms": 1.0,
        "latency_max_ms": 20.0,
        "latency_mean_ms": 10.0,
        "success_rate_pct": 80.0,
        "operations": {
            "a": {
                "total": 10,
                "success": 8,
                "failed": 2,
                "latency_sum_ms": 100.0,
                "latency_mean_ms": 10.0,
            }
        },
    }
    later = {
        "requests_total": 25,
        "requests_success": 20,
        "requests_failed": 5,
        "latency_sum_ms": 250.0,
        "latency_min_ms": 1.0,
        "latency_max_ms": 30.0,
        "latency_mean_ms": 10.0,
        "success_rate_pct": 80.0,
        "operations": {
            "a": {
                "total": 25,
                "success": 20,
                "failed": 5,
                "latency_sum_ms": 250.0,
                "latency_mean_ms": 10.0,
            }
        },
    }
    d = wg.diff_workload_metrics(later, early)
    assert d["requests_total"] == 15
    assert d["requests_success"] == 12
    assert d["requests_failed"] == 3
    assert d["operations"]["a"]["total"] == 15


def test_burst_pattern_summary() -> None:
    scenario = {
        "workload": {
            "burst_pattern": {
                "enabled": True,
                "normal_rps": 5,
                "burst_rps": 20,
                "burst_duration_seconds": 1,
                "cooldown_seconds": 2,
                "cycles": 3,
            }
        }
    }
    s = wg.burst_pattern_summary(scenario)
    assert s is not None
    assert s["burst_rps"] == 20
    assert s["cycles"] == 3


def test_effective_target_rps_fault_max() -> None:
    wg._reset_state()
    wg._fault_phase_active = True
    wg._fault_rps_override = 40
    wg._set_scheduler_target_rps(10)
    try:
        assert wg._effective_target_rps() == 40
        wg._set_scheduler_target_rps(100)
        assert wg._effective_target_rps() == 100
    finally:
        wg._fault_phase_active = False
        wg._fault_rps_override = None
