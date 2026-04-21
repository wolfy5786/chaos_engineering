"""Test orchestrator: loads scenario, sequences stub components, returns run metadata."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, MutableMapping

import yaml

from framework import fault_injector, log_aggregator, report_generator, traffic_monitor, workload_generator
from framework.assertions import evaluate as assertions_evaluate

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunResult:
    success: bool
    run_id: str
    scenario_path: Path
    scenario: Mapping[str, Any]
    json_report: Path
    html_report: Path
    message: str


def _load_scenario(scenario_path: Path) -> Mapping[str, Any]:
    logger.info("orchestrator: loading scenario from %s", scenario_path.resolve())
    raw = yaml.safe_load(scenario_path.read_text(encoding="utf-8"))
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("scenario root must be a mapping")
    logger.info("orchestrator: scenario loaded; top-level keys: %s", list(raw.keys()))
    return raw


def run_pipeline(scenario_path: Path, results_dir: Path | None = None) -> RunResult:
    """Load a scenario, run baseline → fault → recovery phases, then write reports."""
    results_dir = results_dir or Path("results")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    logger.info("orchestrator.run_pipeline enter run_id=%s", run_id)

    scenario = _load_scenario(scenario_path)

    started_at_dt = datetime.now(timezone.utc)
    started_at = started_at_dt.isoformat()

    logger.info("orchestrator: phase baseline")
    fault_injector.baseline(scenario)
    log_aggregator.start(scenario)
    traffic_monitor.start(scenario)
    workload_generator.run_baseline_load(scenario)

    logger.info("orchestrator: phase injection + workload under fault")
    fault_injector.inject(scenario)
    workload_generator.run_under_fault(scenario)

    logger.info("orchestrator: phase recovery + stop workload")
    fault_injector.recover(scenario)
    workload_generator.stop(scenario)

    ended_at_dt = datetime.now(timezone.utc)
    ended_at = ended_at_dt.isoformat()

    logger.info("orchestrator: phase stop monitoring")
    traffic_monitor.stop(scenario)
    log_aggregator.stop(scenario)

    observations: MutableMapping[str, Any] = {
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_seconds": round((ended_at_dt - started_at_dt).total_seconds(), 2),
        "workload": workload_generator.get_metrics(),
        "faults": scenario.get("faults", []),
        "logs": [],
        "traffic": [],
    }

    logger.info("orchestrator: phase analysis (assertions)")
    assertions_evaluate(observations, scenario)

    logger.info("orchestrator: phase report generation")
    json_path, html_path = report_generator.write_reports(
        scenario, observations, results_dir, run_id
    )

    logger.info("orchestrator.run_pipeline exit run_id=%s success=True", run_id)
    return RunResult(
        success=True,
        run_id=run_id,
        scenario_path=scenario_path.resolve(),
        scenario=scenario,
        json_report=json_path,
        html_report=html_path,
        message="Pipeline completed.",
    )
