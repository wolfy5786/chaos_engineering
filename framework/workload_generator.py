"""Threaded HTTP workload generator.

Reads the ``workload`` block from the scenario mapping and drives real HTTP
traffic at a configurable RPS across a pool of worker threads.

Scenario ``workload`` block example::

    workload:
      type: realistic_client
      rps: 10
      num_workers: 5          # optional; defaults to min(rps, 20)
      targets:
        base_url: "http://localhost:8000"
        endpoints:
          login:          "POST /auth/login"
          browse_profile: "GET  /users/1/profile"
          access_data:    "GET  /data"
      operations:
        - login
        - browse_profile
        - access_data

``base_url`` may also be provided via the ``WORKLOAD_BASE_URL`` environment
variable (scenario value takes precedence).
"""

from __future__ import annotations

import logging
import os
import random
import threading
import time
from typing import Any, Mapping, MutableMapping

import requests as _requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level state (reset on each run_baseline_load call)
# ---------------------------------------------------------------------------
_stop_event: threading.Event | None = None
_workers: list[threading.Thread] = []
_metrics: MutableMapping[str, Any] = {}
_metrics_lock: threading.Lock = threading.Lock()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _reset_state() -> None:
    global _stop_event, _workers, _metrics
    _stop_event = threading.Event()
    _workers = []
    _metrics = {
        "requests_total": 0,
        "requests_success": 0,
        "requests_failed": 0,
        "latency_sum_ms": 0.0,
        "latency_min_ms": float("inf"),
        "latency_max_ms": 0.0,
        "operations": {},
    }


def _record(op: str, success: bool, latency_ms: float) -> None:
    with _metrics_lock:
        _metrics["requests_total"] += 1
        if success:
            _metrics["requests_success"] += 1
        else:
            _metrics["requests_failed"] += 1
        _metrics["latency_sum_ms"] += latency_ms
        if latency_ms < _metrics["latency_min_ms"]:
            _metrics["latency_min_ms"] = latency_ms
        if latency_ms > _metrics["latency_max_ms"]:
            _metrics["latency_max_ms"] = latency_ms

        op_stats = _metrics["operations"].setdefault(
            op,
            {"total": 0, "success": 0, "failed": 0, "latency_sum_ms": 0.0},
        )
        op_stats["total"] += 1
        if success:
            op_stats["success"] += 1
        else:
            op_stats["failed"] += 1
        op_stats["latency_sum_ms"] += latency_ms


def _build_session(workload_cfg: Mapping[str, Any]) -> _requests.Session:
    session = _requests.Session()
    headers = workload_cfg.get("headers", {})
    if headers:
        session.headers.update(headers)
    return session


def _worker_loop(
    workload_cfg: Mapping[str, Any],
    stop_event: threading.Event,
    sleep_interval: float,
    worker_id: int,
) -> None:
    """Single worker thread: fires HTTP requests until stop_event is set."""
    operations: list[str] = workload_cfg.get("operations", [])
    targets: Mapping[str, Any] = workload_cfg.get("targets", {})
    endpoints: Mapping[str, str] = targets.get("endpoints", {})
    base_url: str = (
        targets.get("base_url")
        or os.environ.get("WORKLOAD_BASE_URL", "")
    ).rstrip("/")
    timeout: float = float(workload_cfg.get("request_timeout_seconds", 10))

    session = _build_session(workload_cfg)

    if not base_url:
        logger.warning(
            "workload_generator worker-%d: no base_url configured; "
            "requests will be skipped",
            worker_id,
        )

    if not operations:
        logger.warning(
            "workload_generator worker-%d: no operations defined; "
            "worker will idle until stopped",
            worker_id,
        )
        stop_event.wait()
        return

    logger.debug("workload_generator worker-%d: started (interval=%.3fs)", worker_id, sleep_interval)

    while not stop_event.is_set():
        op = random.choice(operations)
        endpoint_spec: str = endpoints.get(op, f"GET /{op}")
        parts = endpoint_spec.split(None, 1)
        method = parts[0].upper() if len(parts) == 2 else "GET"
        path = parts[1].lstrip() if len(parts) == 2 else parts[0]

        url = f"{base_url}{path}" if base_url else path

        t0 = time.monotonic()
        success = False
        status_code: int | None = None

        if base_url:
            try:
                resp = session.request(method, url, timeout=timeout)
                status_code = resp.status_code
                success = resp.status_code < 500
                logger.debug(
                    "workload_generator worker-%d: %s %s -> %d",
                    worker_id,
                    method,
                    url,
                    resp.status_code,
                )
            except _requests.exceptions.Timeout:
                logger.debug(
                    "workload_generator worker-%d: %s %s -> TIMEOUT",
                    worker_id,
                    method,
                    url,
                )
            except _requests.exceptions.ConnectionError:
                logger.debug(
                    "workload_generator worker-%d: %s %s -> CONNECTION_ERROR",
                    worker_id,
                    method,
                    url,
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "workload_generator worker-%d: %s %s -> ERROR %s",
                    worker_id,
                    method,
                    url,
                    exc,
                )
        else:
            # No target configured — simulate the call timing only.
            simulated_ms = random.uniform(5, 50)
            time.sleep(simulated_ms / 1000)
            success = True

        latency_ms = (time.monotonic() - t0) * 1000
        _record(op, success, latency_ms)

        elapsed = time.monotonic() - t0
        wait = max(0.0, sleep_interval - elapsed)
        if wait > 0:
            stop_event.wait(timeout=wait)

    logger.debug("workload_generator worker-%d: stopped", worker_id)
    session.close()


def _start_workers(workload_cfg: Mapping[str, Any]) -> None:
    """Spawn worker threads according to ``workload_cfg``."""
    rps: int = max(1, int(workload_cfg.get("rps", 1)))
    num_workers: int = int(workload_cfg.get("num_workers", min(rps, 20)))
    num_workers = max(1, num_workers)

    # Each worker fires at a rate of (rps / num_workers) req/s.
    sleep_interval: float = num_workers / rps

    logger.info(
        "workload_generator: spawning %d workers at %.1f rps "
        "(interval=%.3fs per worker)",
        num_workers,
        rps,
        sleep_interval,
    )

    assert _stop_event is not None  # guaranteed by _reset_state()
    for i in range(num_workers):
        t = threading.Thread(
            target=_worker_loop,
            args=(workload_cfg, _stop_event, sleep_interval, i),
            daemon=True,
            name=f"workload-worker-{i}",
        )
        _workers.append(t)
        t.start()


def _log_metrics_summary() -> None:
    total = _metrics.get("requests_total", 0)
    success = _metrics.get("requests_success", 0)
    failed = _metrics.get("requests_failed", 0)
    lat_sum = _metrics.get("latency_sum_ms", 0.0)
    lat_min = _metrics.get("latency_min_ms", 0.0)
    lat_max = _metrics.get("latency_max_ms", 0.0)
    mean_lat = (lat_sum / total) if total > 0 else 0.0
    success_pct = (success / total * 100) if total > 0 else 0.0

    logger.info(
        "workload_generator metrics: total=%d success=%d (%.1f%%) failed=%d "
        "latency mean=%.1fms min=%.1fms max=%.1fms",
        total,
        success,
        success_pct,
        failed,
        mean_lat,
        lat_min if lat_min != float("inf") else 0.0,
        lat_max,
    )

    for op, stats in _metrics.get("operations", {}).items():
        op_total = stats["total"]
        op_success = stats["success"]
        op_mean = (stats["latency_sum_ms"] / op_total) if op_total > 0 else 0.0
        logger.info(
            "workload_generator metrics [%s]: total=%d success=%d mean_latency=%.1fms",
            op,
            op_total,
            op_success,
            op_mean,
        )


# ---------------------------------------------------------------------------
# Public API (called by orchestrator)
# ---------------------------------------------------------------------------

def run_baseline_load(scenario: Mapping[str, Any]) -> None:
    """Start worker threads and begin driving baseline load.

    Non-blocking: returns immediately after spawning threads.  The orchestrator
    controls how long the baseline phase lasts before calling ``stop``.
    """
    logger.info("workload_generator.run_baseline_load enter")
    _reset_state()

    workload_cfg: Mapping[str, Any] = scenario.get("workload", {})
    if not workload_cfg:
        logger.warning(
            "workload_generator: no 'workload' key in scenario; "
            "no load will be generated"
        )
        logger.info("workload_generator.run_baseline_load exit (no workload config)")
        return

    _start_workers(workload_cfg)
    logger.info("workload_generator.run_baseline_load exit (%d workers running)", len(_workers))


def run_under_fault(scenario: Mapping[str, Any]) -> None:
    """Continue driving load during the fault-injection phase.

    Workers are already running from ``run_baseline_load``; this function
    logs the phase transition and optionally increases load when the scenario
    specifies a ``fault_rps`` override.
    """
    logger.info("workload_generator.run_under_fault enter")

    workload_cfg: Mapping[str, Any] = scenario.get("workload", {})
    fault_rps = workload_cfg.get("fault_rps")

    if _stop_event is None or _stop_event.is_set():
        logger.warning(
            "workload_generator.run_under_fault: workers are not running; "
            "starting fresh for fault phase"
        )
        run_baseline_load(scenario)
        return

    if fault_rps is not None:
        extra_workers = max(0, int(fault_rps) - len(_workers))
        if extra_workers > 0:
            rps = max(1, int(workload_cfg.get("rps", 1)))
            num_workers = int(workload_cfg.get("num_workers", min(rps, 20)))
            sleep_interval = num_workers / rps
            logger.info(
                "workload_generator: fault phase — adding %d extra workers "
                "(fault_rps=%s)",
                extra_workers,
                fault_rps,
            )
            assert _stop_event is not None
            for i in range(extra_workers):
                idx = len(_workers)
                t = threading.Thread(
                    target=_worker_loop,
                    args=(workload_cfg, _stop_event, sleep_interval, idx),
                    daemon=True,
                    name=f"workload-fault-worker-{i}",
                )
                _workers.append(t)
                t.start()
    else:
        logger.info(
            "workload_generator: fault phase — continuing with %d existing workers",
            len(_workers),
        )

    logger.info("workload_generator.run_under_fault exit")


def stop(scenario: Mapping[str, Any]) -> None:  # noqa: ARG001
    """Signal all workers to stop, wait for them to finish, then log metrics."""
    logger.info("workload_generator.stop enter (%d workers)", len(_workers))

    if _stop_event is not None:
        _stop_event.set()

    join_timeout = float((scenario.get("workload") or {}).get("stop_timeout_seconds", 10))
    for t in _workers:
        t.join(timeout=join_timeout)
        if t.is_alive():
            logger.warning("workload_generator: worker %s did not stop in time", t.name)

    _log_metrics_summary()
    logger.info("workload_generator.stop exit")


def get_metrics() -> dict[str, Any]:
    """Return a snapshot of workload counters and latency stats (thread-safe).

    Safe to call after :func:`stop`; if no workload ran, returns zeroed metrics.
    """
    with _metrics_lock:
        if not _metrics or "requests_total" not in _metrics:
            return {
                "requests_total": 0,
                "requests_success": 0,
                "requests_failed": 0,
                "latency_sum_ms": 0.0,
                "latency_min_ms": 0.0,
                "latency_max_ms": 0.0,
                "latency_mean_ms": 0.0,
                "success_rate_pct": 0.0,
                "operations": {},
            }
        total = int(_metrics.get("requests_total", 0))
        lat_sum = float(_metrics.get("latency_sum_ms", 0.0))
        lat_min_raw = _metrics.get("latency_min_ms", float("inf"))
        snapshot: dict[str, Any] = {
            "requests_total": total,
            "requests_success": int(_metrics.get("requests_success", 0)),
            "requests_failed": int(_metrics.get("requests_failed", 0)),
            "latency_sum_ms": lat_sum,
            "latency_max_ms": float(_metrics.get("latency_max_ms", 0.0)),
            "operations": {
                op: dict(stats) for op, stats in _metrics.get("operations", {}).items()
            },
        }

    lat_min = float(lat_min_raw) if lat_min_raw != float("inf") else 0.0
    snapshot["latency_min_ms"] = lat_min
    snapshot["latency_mean_ms"] = (lat_sum / total) if total > 0 else 0.0
    snapshot["success_rate_pct"] = (
        (snapshot["requests_success"] / total * 100.0) if total > 0 else 0.0
    )

    ops_out: dict[str, Any] = {}
    for op, s in snapshot.get("operations", {}).items():
        op_total = int(s.get("total", 0))
        lat_op_sum = float(s.get("latency_sum_ms", 0.0))
        ops_out[op] = {
            **s,
            "latency_mean_ms": (lat_op_sum / op_total) if op_total > 0 else 0.0,
        }
    snapshot["operations"] = ops_out
    return snapshot
