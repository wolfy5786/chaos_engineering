"""Smoke tests for orchestrator workload phases and report payload."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from framework.orchestrator import run_pipeline


def test_run_pipeline_includes_phases_and_assertions(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CHAOS_BACKEND", "null")

    scenario_path = tmp_path / "scenario.yaml"
    scenario = {
        "name": "orch_load_smoke",
        "phases": {
            "baseline_duration_seconds": 0.12,
            "injection_duration_seconds": 0.12,
        },
        "workload": {
            "rps": 40,
            "burst_pattern": {
                "enabled": True,
                "normal_rps": 20,
                "burst_rps": 35,
                "burst_duration_seconds": 0.05,
                "cooldown_seconds": 0.05,
                "cycles": None,
            },
            "targets": {
                "endpoints": {"x": "GET /x"},
            },
            "operations": ["x"],
        },
        "faults": [],
        "assertions": {"load": {"min_requests_total": 2}},
    }
    scenario_path.write_text(yaml.safe_dump(scenario), encoding="utf-8")

    results_dir = tmp_path / "results"
    result = run_pipeline(scenario_path, results_dir)

    payload = json.loads(result.json_report.read_text(encoding="utf-8"))
    assert "workload_phases" in payload
    assert "deltas" in payload["workload_phases"]
    assert "baseline_window" in payload["workload_phases"]["deltas"]
    assert "assertion_results" in payload
    assert payload["assertion_results"].get("overall_passed") is True
    assert payload["workload"]["requests_total"] >= 2
