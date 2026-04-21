"""Report generator: structured JSON + self-contained HTML under results/."""

from __future__ import annotations

import html
import json
import logging
from pathlib import Path
from typing import Any, Mapping, Tuple

logger = logging.getLogger(__name__)


def _scenario_description(scenario: Mapping[str, Any]) -> str:
    raw = scenario.get("description", "")
    if raw is None:
        return ""
    return str(raw).strip()


def _fault_rows(faults: Any) -> list[dict[str, Any]]:
    if not isinstance(faults, list):
        return []
    rows: list[dict[str, Any]] = []
    for i, f in enumerate(faults):
        if not isinstance(f, dict):
            rows.append({"index": i + 1, "type": str(f), "target": "", "delay_seconds": ""})
            continue
        target = f.get("target", {})
        if isinstance(target, Mapping):
            ns = target.get("namespace", "")
            sel = target.get("label_selector", "")
            target_str = f"{ns} {sel}".strip() or json.dumps(dict(target), sort_keys=True)
        else:
            target_str = str(target)
        rows.append(
            {
                "index": i + 1,
                "type": f.get("type", ""),
                "target": target_str,
                "delay_seconds": f.get("delay_seconds", ""),
            }
        )
    return rows


def _build_json_payload(
    run_id: str,
    scenario: Mapping[str, Any],
    observations: Mapping[str, Any],
) -> dict[str, Any]:
    desc = _scenario_description(scenario)
    return {
        "run_id": run_id,
        "scenario_name": scenario.get("name", "unknown"),
        "scenario_description": desc,
        "started_at": observations.get("started_at"),
        "ended_at": observations.get("ended_at"),
        "duration_seconds": observations.get("duration_seconds"),
        "faults": observations.get("faults", []),
        "workload": observations.get("workload", {}),
        "logs": observations.get("logs", []),
        "traffic": observations.get("traffic", []),
    }


def _format_ops_table_rows(workload: Mapping[str, Any]) -> str:
    ops = workload.get("operations") or {}
    if not isinstance(ops, dict) or not ops:
        return "<tr><td colspan='5' class='muted'>No per-operation data</td></tr>"
    lines: list[str] = []
    for op in sorted(ops.keys()):
        s = ops[op]
        if not isinstance(s, Mapping):
            continue
        total = s.get("total", 0)
        succ = s.get("success", 0)
        fail = s.get("failed", 0)
        mean_lat = s.get("latency_mean_ms", 0)
        lines.append(
            "<tr>"
            f"<td>{html.escape(str(op))}</td>"
            f"<td class='num'>{html.escape(str(total))}</td>"
            f"<td class='num'>{html.escape(str(succ))}</td>"
            f"<td class='num'>{html.escape(str(fail))}</td>"
            f"<td class='num'>{html.escape(f'{float(mean_lat):.2f}')}</td>"
            "</tr>"
        )
    return "\n".join(lines) if lines else "<tr><td colspan='5' class='muted'>No per-operation data</td></tr>"


def _format_fault_rows_html(faults: Any) -> str:
    rows = _fault_rows(faults)
    if not rows:
        return "<tr><td colspan='4' class='muted'>No faults in scenario</td></tr>"
    lines = []
    for r in rows:
        lines.append(
            "<tr>"
            f"<td class='num'>{r['index']}</td>"
            f"<td>{html.escape(str(r['type']))}</td>"
            f"<td>{html.escape(str(r['target']))}</td>"
            f"<td class='num'>{html.escape(str(r['delay_seconds']))}</td>"
            "</tr>"
        )
    return "\n".join(lines)


def _build_html(run_id: str, payload: Mapping[str, Any]) -> str:
    name = html.escape(str(payload.get("scenario_name", "unknown")))
    desc_raw = payload.get("scenario_description") or ""
    desc = html.escape(str(desc_raw)) if desc_raw else ""
    wl = payload.get("workload") or {}
    if not isinstance(wl, Mapping):
        wl = {}

    total = wl.get("requests_total", 0)
    succ_pct = wl.get("success_rate_pct", 0.0)
    mean_lat = wl.get("latency_mean_ms", 0.0)
    min_lat = wl.get("latency_min_ms", 0.0)
    max_lat = wl.get("latency_max_ms", 0.0)
    succ_n = wl.get("requests_success", 0)
    fail_n = wl.get("requests_failed", 0)

    css = """
    body { font-family: system-ui, Segoe UI, Roboto, sans-serif; margin: 2rem; color: #1a1a1a; line-height: 1.5; }
    h1 { font-size: 1.5rem; margin-bottom: 0.25rem; }
    .meta { color: #444; font-size: 0.9rem; margin-bottom: 1.5rem; }
    .desc { white-space: pre-wrap; max-width: 56rem; margin-bottom: 1.5rem; }
    table { border-collapse: collapse; width: 100%; max-width: 56rem; margin-bottom: 2rem; }
    th, td { border: 1px solid #ccc; padding: 0.5rem 0.75rem; text-align: left; }
    th { background: #f4f4f4; font-weight: 600; }
    .num { text-align: right; font-variant-numeric: tabular-nums; }
    .muted { color: #666; font-style: italic; }
    h2 { font-size: 1.15rem; margin-top: 1.5rem; margin-bottom: 0.5rem; }
    """

    desc_block = f'<p class="desc">{desc}</p>' if desc else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Chaos report — {html.escape(run_id)}</title>
  <style>{css}</style>
</head>
<body>
  <h1>{name}</h1>
  <p class="meta">Run ID: {html.escape(run_id)}<br>
  Started: {html.escape(str(payload.get("started_at", "")))}<br>
  Ended: {html.escape(str(payload.get("ended_at", "")))}<br>
  Duration: {html.escape(str(payload.get("duration_seconds", "")))} s</p>
  {desc_block}

  <h2>Workload summary</h2>
  <table>
    <thead><tr><th>Metric</th><th class="num">Value</th></tr></thead>
    <tbody>
      <tr><td>Total requests</td><td class="num">{html.escape(str(total))}</td></tr>
      <tr><td>Success</td><td class="num">{html.escape(str(succ_n))}</td></tr>
      <tr><td>Failed</td><td class="num">{html.escape(str(fail_n))}</td></tr>
      <tr><td>Success rate</td><td class="num">{html.escape(f"{float(succ_pct):.2f}")}%</td></tr>
      <tr><td>Latency mean</td><td class="num">{html.escape(f"{float(mean_lat):.2f}")} ms</td></tr>
      <tr><td>Latency min</td><td class="num">{html.escape(f"{float(min_lat):.2f}")} ms</td></tr>
      <tr><td>Latency max</td><td class="num">{html.escape(f"{float(max_lat):.2f}")} ms</td></tr>
    </tbody>
  </table>

  <h2>Injected faults</h2>
  <table>
    <thead><tr><th class="num">#</th><th>Type</th><th>Target</th><th class="num">Delay (s)</th></tr></thead>
    <tbody>
      {_format_fault_rows_html(payload.get("faults"))}
    </tbody>
  </table>

  <h2>Per-operation breakdown</h2>
  <table>
    <thead><tr><th>Operation</th><th class="num">Total</th><th class="num">Success</th><th class="num">Failed</th><th class="num">Mean latency (ms)</th></tr></thead>
    <tbody>
      {_format_ops_table_rows(wl)}
    </tbody>
  </table>
</body>
</html>
"""


def write_reports(
    scenario: Mapping[str, Any],
    observations: Mapping[str, Any],
    results_dir: Path,
    run_id: str,
) -> Tuple[Path, Path]:
    logger.info("report_generator.write_reports enter")
    results_dir.mkdir(parents=True, exist_ok=True)
    stem = f"chaos-report-{run_id}"
    json_path = results_dir / f"{stem}.json"
    html_path = results_dir / f"{stem}.html"

    payload = _build_json_payload(run_id, scenario, observations)
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    html_path.write_text(_build_html(run_id, payload), encoding="utf-8")

    logger.info("report_generator artifacts: %s, %s", json_path, html_path)
    logger.info("report_generator.write_reports exit")
    return json_path, html_path
