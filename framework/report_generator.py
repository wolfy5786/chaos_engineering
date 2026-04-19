"""Stub report generator: writes minimal placeholder HTML + JSON under results/."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Mapping, Tuple

logger = logging.getLogger(__name__)


def write_reports(
    scenario: Mapping[str, Any],
    observations: Mapping[str, Any],
    results_dir: Path,
    run_id: str,
) -> Tuple[Path, Path]:
    logger.info("report_generator.write_reports enter")
    results_dir.mkdir(parents=True, exist_ok=True)
    stem = f"skeleton-report-{run_id}"
    json_path = results_dir / f"{stem}.json"
    html_path = results_dir / f"{stem}.html"
    payload = {
        "run_id": run_id,
        "scenario_name": scenario.get("name", "unknown"),
        "stub": True,
        "observation_keys": list(observations.keys()),
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    html_path.write_text(
        "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Skeleton report</title></head>"
        f"<body><h1>Skeleton report</h1><p>Run: {run_id}</p></body></html>",
        encoding="utf-8",
    )
    logger.info("report_generator stub artifacts: %s, %s", json_path, html_path)
    logger.debug("report_generator.write_reports (stub: full HTML/JSON analytics in real impl)")
    logger.info("report_generator.write_reports exit")
    return json_path, html_path
