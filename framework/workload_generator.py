"""Threaded HTTP workload generator.

Reads the ``workload`` block from the scenario mapping and drives real HTTP
traffic at a configurable RPS across a pool of worker threads.

Scenario ``workload`` block example::

    workload:
      type: realistic_client
      rps: 10
      num_workers: 5          # optional; defaults to min(rps, 20)
      selection: random       # or round_robin (default: random)
      targets:
        base_url: "http://localhost:8000"
        endpoints:
          # Short form — no body:
          health: "GET /health"
          chain:  "GET /chain"
          # Full form — supply JSON body (and optional headers/params).
          # ${VAR} / ${VAR:default} are expanded from the process environment,
          # so credentials can live in .env instead of the scenario file.
          login:
            method: POST
            path: /auth/login
            body:
              email: "${LOGIN_EMAIL}"
              password: "${LOGIN_PASSWORD}"
      operations:
        - health
        - chain
        - login

``base_url`` may also be provided via the ``WORKLOAD_BASE_URL`` environment
variable (scenario value takes precedence).

Optional **burst** traffic (Phase 1 load testing)::

    workload:
      rps: 5
      burst_pattern:
        enabled: true
        normal_rps: 5          # optional; defaults to workload.rps
        burst_rps: 25
        burst_duration_seconds: 3
        cooldown_seconds: 5   # time at normal_rps between bursts
        cycles: null         # null = repeat until stop; integer = burst rounds then stay at normal

During the fault-injection phase, ``fault_rps`` (if set) raises the effective
target to ``max(current_burst_rps, fault_rps)`` without spawning extra threads.

Workers never drop an operation from their rotation on failure: every worker
keeps issuing requests to every configured endpoint for the whole run.
Per-operation counters (``_metrics["operations"][op]``) and the summary log
line make it easy to see which endpoint, if any, is failing.
"""

from __future__ import annotations

import copy
import itertools
import logging
import os
import random
import re
import threading
import time
from typing import Any, Mapping, MutableMapping

import requests as _requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Endpoint parsing and ${VAR}/${VAR:default} substitution
# ---------------------------------------------------------------------------

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::([^}]*))?\}")


def _expand_env(value: Any) -> Any:
    """Recursively replace ``${NAME}`` / ``${NAME:default}`` in strings inside
    dicts, lists, and scalars. Non-string leaves are returned unchanged.
    """
    if isinstance(value, str):
        def _sub(m: re.Match[str]) -> str:
            name, default = m.group(1), m.group(2)
            env_val = os.environ.get(name)
            if env_val is not None:
                return env_val
            return default if default is not None else ""
        return _ENV_PATTERN.sub(_sub, value)
    if isinstance(value, Mapping):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def _parse_endpoint_spec(op: str, spec: Any) -> dict[str, Any]:
    """Normalize a scenario endpoint entry to ``{method, path, body, headers, params}``.

    Accepts:
    - ``"POST /auth/login"`` (short form; no body).
    - ``{method, path, body?, headers?, params?}`` (full form).

    ``${VAR}`` tokens in every string field are expanded from the process
    environment.
    """
    if isinstance(spec, str):
        parts = spec.split(None, 1)
        if len(parts) == 2:
            method, path = parts[0].upper(), parts[1].lstrip()
        else:
            method, path = "GET", parts[0]
        return {
            "method": method,
            "path": _expand_env(path),
            "body": None,
            "headers": None,
            "params": None,
        }
    if isinstance(spec, Mapping):
        method = str(spec.get("method", "GET")).upper()
        path = spec.get("path")
        if not isinstance(path, str) or not path:
            raise ValueError(
                f"workload endpoint {op!r}: 'path' is required (got {path!r})"
            )
        body = spec.get("body")
        headers = spec.get("headers")
        params = spec.get("params")
        return {
            "method": method,
            "path": _expand_env(path),
            "body": _expand_env(copy.deepcopy(body)) if body is not None else None,
            "headers": _expand_env(copy.deepcopy(headers)) if headers else None,
            "params": _expand_env(copy.deepcopy(params)) if params else None,
        }
    raise TypeError(
        f"workload endpoint {op!r}: expected string or mapping, got {type(spec).__name__}"
    )


def _compile_endpoints(workload_cfg: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Pre-parse every entry in ``targets.endpoints`` once per run."""
    targets: Mapping[str, Any] = workload_cfg.get("targets") or {}
    raw: Mapping[str, Any] = targets.get("endpoints") or {}
    compiled: dict[str, dict[str, Any]] = {}
    for op, spec in raw.items():
        try:
            compiled[op] = _parse_endpoint_spec(op, spec)
        except (TypeError, ValueError) as e:
            logger.error("workload_generator: %s", e)
            raise
    return compiled

# ---------------------------------------------------------------------------
# Module-level state (reset on each run_baseline_load call)
# ---------------------------------------------------------------------------
_stop_event: threading.Event | None = None
_workers: list[threading.Thread] = []
_burst_thread: threading.Thread | None = None
_metrics: MutableMapping[str, Any] = {}
_metrics_lock: threading.Lock = threading.Lock()
_target_rps_lock: threading.Lock = threading.Lock()
_scheduler_target_rps: int = 1
_fault_phase_active: bool = False
_fault_rps_override: int | None = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _reset_state() -> None:
    global _stop_event, _workers, _burst_thread, _metrics
    global _fault_phase_active, _fault_rps_override, _scheduler_target_rps
    _join_burst_thread()
    _burst_thread = None
    _fault_phase_active = False
    _fault_rps_override = None
    _scheduler_target_rps = 1
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


def _join_burst_thread() -> None:
    global _burst_thread
    t = _burst_thread
    if t is not None and t.is_alive():
        t.join(timeout=5.0)
        if t.is_alive():
            logger.warning("workload_generator: burst scheduler thread did not stop in time")


def _set_scheduler_target_rps(value: int) -> None:
    global _scheduler_target_rps
    with _target_rps_lock:
        _scheduler_target_rps = max(1, int(value))


def _effective_target_rps() -> int:
    """Burst scheduler RPS, optionally raised during fault phase by ``fault_rps``."""
    with _target_rps_lock:
        base = max(1, int(_scheduler_target_rps))
        if _fault_phase_active and _fault_rps_override is not None:
            return max(base, max(1, int(_fault_rps_override)))
        return base


def _worker_pacing_interval(workload_cfg: Mapping[str, Any], num_workers: int) -> float:
    """Seconds to wait between requests for one worker (global pacing target).

    When ``burst_pattern`` is disabled, pacing uses ``workload_cfg['rps']`` so unit
    tests that call :func:`_worker_loop` directly (without :func:`run_baseline_load`)
    still hit the configured RPS. When burst is enabled, uses the live scheduler +
    optional ``fault_rps`` (see :func:`_effective_target_rps`).
    """
    bp_raw = workload_cfg.get("burst_pattern")
    burst_on = isinstance(bp_raw, Mapping) and bool(bp_raw.get("enabled"))
    if burst_on:
        eff = _effective_target_rps()
    else:
        eff = max(1, int(workload_cfg.get("rps", 1)))
        if _fault_phase_active and _fault_rps_override is not None:
            eff = max(eff, max(1, int(_fault_rps_override)))
    return num_workers / max(1, eff)


def _sleep_chunked(stop_event: threading.Event, total_seconds: float, step: float = 0.05) -> bool:
    """Sleep up to ``total_seconds`` unless ``stop_event`` is set. Returns False if stopped."""
    if total_seconds <= 0:
        return not stop_event.is_set()
    end = time.monotonic() + total_seconds
    while not stop_event.is_set():
        now = time.monotonic()
        if now >= end:
            break
        remaining = min(step, end - now)
        if stop_event.wait(timeout=remaining):
            return False
    return not stop_event.is_set()


def _burst_scheduler_loop(workload_cfg: Mapping[str, Any], stop_event: threading.Event) -> None:
    """Background loop: alternate normal_rps and burst_rps for stress / burst patterns."""
    bp_raw = workload_cfg.get("burst_pattern")
    if not isinstance(bp_raw, Mapping) or not bp_raw.get("enabled"):
        return

    base_rps = max(1, int(workload_cfg.get("rps", 1)))
    normal_rps = max(1, int(bp_raw.get("normal_rps", base_rps)))
    burst_rps = max(1, int(bp_raw.get("burst_rps", normal_rps * 2)))
    burst_dur = float(bp_raw.get("burst_duration_seconds", 1.0))
    cooldown = float(bp_raw.get("cooldown_seconds", 1.0))
    cycles_raw = bp_raw.get("cycles")
    cycles: int | None = None if cycles_raw is None else max(0, int(cycles_raw))

    logger.info(
        "workload_generator burst_pattern: normal=%s burst=%s cooldown=%.2fs burst_dur=%.2fs cycles=%s",
        normal_rps,
        burst_rps,
        cooldown,
        burst_dur,
        cycles_raw,
    )

    round_n = 0
    while not stop_event.is_set():
        _set_scheduler_target_rps(normal_rps)
        if not _sleep_chunked(stop_event, cooldown):
            break
        if stop_event.is_set():
            break
        _set_scheduler_target_rps(burst_rps)
        if not _sleep_chunked(stop_event, burst_dur):
            break
        round_n += 1
        if cycles is not None and round_n >= cycles:
            _set_scheduler_target_rps(normal_rps)
            break

    _set_scheduler_target_rps(normal_rps)


def _record(
    op: str,
    success: bool,
    latency_ms: float,
    status_code: int | None = None,
) -> None:
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
            {
                "total": 0,
                "success": 0,
                "failed": 0,
                "latency_sum_ms": 0.0,
                "status_counts": {},
            },
        )
        op_stats["total"] += 1
        if success:
            op_stats["success"] += 1
        else:
            op_stats["failed"] += 1
        op_stats["latency_sum_ms"] += latency_ms
        if status_code is not None:
            key = str(status_code)
            op_stats.setdefault("status_counts", {})
            op_stats["status_counts"][key] = op_stats["status_counts"].get(key, 0) + 1


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
    """Single worker thread: fires HTTP requests until stop_event is set.

    The worker keeps hitting every configured operation for the duration of
    the run. Failures (timeouts, connection errors, non-2xx) never remove an
    operation from the rotation — they are counted and the worker continues.
    """
    operations: list[str] = list(workload_cfg.get("operations", []))
    targets: Mapping[str, Any] = workload_cfg.get("targets", {})
    compiled_endpoints = _compile_endpoints(workload_cfg)
    base_url: str = (
        targets.get("base_url")
        or os.environ.get("WORKLOAD_BASE_URL", "")
    ).rstrip("/")
    timeout: float = float(workload_cfg.get("request_timeout_seconds", 10))
    selection: str = str(workload_cfg.get("selection", "random")).lower()
    if selection not in {"random", "round_robin"}:
        logger.warning(
            "workload_generator worker-%d: unknown selection=%r; falling back to 'random'",
            worker_id,
            selection,
        )
        selection = "random"

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

    # Offset per worker so round-robin doesn't line workers up on the same op.
    rr_iter = itertools.cycle(operations[worker_id % len(operations):] + operations[: worker_id % len(operations)])

    rps_cfg = max(1, int(workload_cfg.get("rps", 1)))
    num_workers: int = max(1, int(workload_cfg.get("num_workers", min(rps_cfg, 20))))
    # sleep_interval arg kept for API compatibility; pacing uses burst/fault effective RPS.
    _ = sleep_interval

    logger.debug(
        "workload_generator worker-%d: started (selection=%s, ops=%s, num_workers=%d)",
        worker_id,
        selection,
        operations,
        num_workers,
    )

    while not stop_event.is_set():
        if selection == "round_robin":
            op = next(rr_iter)
        else:
            op = random.choice(operations)

        ep = compiled_endpoints.get(op) or _parse_endpoint_spec(op, f"GET /{op}")
        method = ep["method"]
        path = ep["path"]
        body = ep["body"]
        headers = ep["headers"]
        params = ep["params"]

        url = f"{base_url}{path}" if base_url else path

        t0 = time.monotonic()
        success = False
        status_code: int | None = None

        if base_url:
            try:
                req_kwargs: dict[str, Any] = {"timeout": timeout}
                if body is not None:
                    req_kwargs["json"] = body
                if headers:
                    req_kwargs["headers"] = headers
                if params:
                    req_kwargs["params"] = params
                resp = session.request(method, url, **req_kwargs)
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
        _record(op, success, latency_ms, status_code=status_code)

        interval = _worker_pacing_interval(workload_cfg, num_workers)
        elapsed = time.monotonic() - t0
        wait = max(0.0, interval - elapsed)
        if wait > 0:
            stop_event.wait(timeout=wait)

    logger.debug("workload_generator worker-%d: stopped", worker_id)
    session.close()


def _start_workers(workload_cfg: Mapping[str, Any]) -> None:
    """Spawn worker threads according to ``workload_cfg``."""
    rps: int = max(1, int(workload_cfg.get("rps", 1)))
    explicit_workers = "num_workers" in workload_cfg
    num_workers: int = int(workload_cfg.get("num_workers", min(rps, 20)))
    num_workers = max(1, num_workers)

    bp_raw = workload_cfg.get("burst_pattern")
    burst_on = isinstance(bp_raw, Mapping) and bool(bp_raw.get("enabled"))
    peak_rps = rps
    if burst_on:
        normal_rps = max(1, int(bp_raw.get("normal_rps", rps)))
        peak_rps = max(peak_rps, normal_rps, int(bp_raw.get("burst_rps", normal_rps * 2)))
    fault_peak = workload_cfg.get("fault_rps")
    if fault_peak is not None:
        peak_rps = max(peak_rps, int(fault_peak))

    if not explicit_workers and peak_rps > num_workers:
        num_workers = max(num_workers, min(peak_rps, 20))

    if isinstance(workload_cfg, MutableMapping):
        workload_cfg["num_workers"] = num_workers

    # Each worker fires at a rate of (effective_rps / num_workers) req/s.
    sleep_interval: float = num_workers / rps
    _set_scheduler_target_rps(rps)
    if burst_on:
        _set_scheduler_target_rps(max(1, int(bp_raw.get("normal_rps", rps))))

    logger.info(
        "workload_generator: spawning %d workers at initial %.1f rps "
        "(interval=%.3fs per worker; burst=%s)",
        num_workers,
        rps,
        sleep_interval,
        burst_on,
    )

    assert _stop_event is not None  # guaranteed by _reset_state()
    global _burst_thread
    if burst_on:
        _burst_thread = threading.Thread(
            target=_burst_scheduler_loop,
            args=(workload_cfg, _stop_event),
            daemon=True,
            name="workload-burst-scheduler",
        )
        _burst_thread.start()

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
        status_counts = stats.get("status_counts") or {}
        status_str = (
            " status=" + ",".join(f"{k}:{v}" for k, v in sorted(status_counts.items()))
            if status_counts
            else ""
        )
        logger.info(
            "workload_generator metrics [%s]: total=%d success=%d mean_latency=%.1fms%s",
            op,
            op_total,
            op_success,
            op_mean,
            status_str,
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

    global _fault_phase_active, _fault_rps_override

    workload_cfg: Mapping[str, Any] = scenario.get("workload", {})
    fault_rps = workload_cfg.get("fault_rps")

    if _stop_event is None or _stop_event.is_set():
        logger.warning(
            "workload_generator.run_under_fault: workers are not running; "
            "starting fresh for fault phase"
        )
        run_baseline_load(scenario)

    _fault_phase_active = True
    _fault_rps_override = int(fault_rps) if fault_rps is not None else None

    if _fault_rps_override is not None:
        logger.info(
            "workload_generator: fault phase — effective rps >= %s (max with burst schedule)",
            _fault_rps_override,
        )
    else:
        logger.info(
            "workload_generator: fault phase — continuing with %d workers (burst schedule only)",
            len(_workers),
        )

    logger.info("workload_generator.run_under_fault exit")


def stop(scenario: Mapping[str, Any]) -> None:  # noqa: ARG001
    """Signal all workers to stop, wait for them to finish, then log metrics."""
    global _fault_phase_active, _fault_rps_override
    logger.info("workload_generator.stop enter (%d workers)", len(_workers))

    if _stop_event is not None:
        _stop_event.set()

    join_timeout = float((scenario.get("workload") or {}).get("stop_timeout_seconds", 10))
    for t in _workers:
        t.join(timeout=join_timeout)
        if t.is_alive():
            logger.warning("workload_generator: worker %s did not stop in time", t.name)

    _join_burst_thread()
    _fault_phase_active = False
    _fault_rps_override = None

    _log_metrics_summary()
    logger.info("workload_generator.stop exit")


def _metrics_to_public_dict(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Build the same shape as :func:`get_metrics` from raw counter dict."""
    total = int(raw.get("requests_total", 0))
    lat_sum = float(raw.get("latency_sum_ms", 0.0))
    lat_min_raw = raw.get("latency_min_ms", float("inf"))
    lat_min = float(lat_min_raw) if lat_min_raw != float("inf") else 0.0
    ops_out: dict[str, Any] = {}
    for op, s in (raw.get("operations") or {}).items():
        if not isinstance(s, Mapping):
            continue
        op_total = int(s.get("total", 0))
        lat_op_sum = float(s.get("latency_sum_ms", 0.0))
        ops_out[str(op)] = {
            **dict(s),
            "latency_mean_ms": (lat_op_sum / op_total) if op_total > 0 else 0.0,
        }
    return {
        "requests_total": total,
        "requests_success": int(raw.get("requests_success", 0)),
        "requests_failed": int(raw.get("requests_failed", 0)),
        "latency_sum_ms": lat_sum,
        "latency_min_ms": lat_min,
        "latency_max_ms": float(raw.get("latency_max_ms", 0.0)),
        "latency_mean_ms": (lat_sum / total) if total > 0 else 0.0,
        "success_rate_pct": (
            (int(raw.get("requests_success", 0)) / total * 100.0) if total > 0 else 0.0
        ),
        "operations": ops_out,
    }


def snapshot_metrics() -> dict[str, Any]:
    """Thread-safe snapshot of cumulative metrics (same shape as :func:`get_metrics`)."""
    with _metrics_lock:
        if not _metrics or "requests_total" not in _metrics:
            return _metrics_to_public_dict({})
        raw = copy.deepcopy(dict(_metrics))
    return _metrics_to_public_dict(raw)


def burst_pattern_summary(scenario: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return burst config metadata for reports, or None if disabled / missing."""
    workload_cfg = scenario.get("workload")
    if not isinstance(workload_cfg, Mapping):
        return None
    bp = workload_cfg.get("burst_pattern")
    if not isinstance(bp, Mapping) or not bp.get("enabled"):
        return None
    return {
        "enabled": True,
        "normal_rps": bp.get("normal_rps"),
        "burst_rps": bp.get("burst_rps"),
        "burst_duration_seconds": bp.get("burst_duration_seconds"),
        "cooldown_seconds": bp.get("cooldown_seconds"),
        "cycles": bp.get("cycles"),
    }


def diff_workload_metrics(
    later: Mapping[str, Any], earlier: Mapping[str, Any]
) -> dict[str, Any]:
    """Subtract earlier cumulative snapshot from later (requests and latency sums).

    Both arguments should be public metric dicts (as returned by :func:`snapshot_metrics`).
    Per-operation ``status_counts`` are omitted from the delta.
    """
    def _sub_int(a: str) -> int:
        return max(0, int(later.get(a, 0)) - int(earlier.get(a, 0)))

    tot = _sub_int("requests_total")
    succ = _sub_int("requests_success")
    fail = _sub_int("requests_failed")
    lat_sum = max(
        0.0,
        float(later.get("latency_sum_ms", 0.0)) - float(earlier.get("latency_sum_ms", 0.0)),
    )

    ops_later = later.get("operations") or {}
    ops_earlier = earlier.get("operations") or {}
    ops_delta: dict[str, Any] = {}
    if isinstance(ops_later, dict):
        for op, s2 in ops_later.items():
            if not isinstance(s2, Mapping):
                continue
            s1: Mapping[str, Any] = {}
            if isinstance(ops_earlier, dict):
                raw1 = ops_earlier.get(op)
                if isinstance(raw1, Mapping):
                    s1 = raw1
            ot = max(0, int(s2.get("total", 0)) - int(s1.get("total", 0)))
            osucc = max(0, int(s2.get("success", 0)) - int(s1.get("success", 0)))
            ofail = max(0, int(s2.get("failed", 0)) - int(s1.get("failed", 0)))
            olat = max(0.0, float(s2.get("latency_sum_ms", 0.0)) - float(s1.get("latency_sum_ms", 0.0)))
            ops_delta[str(op)] = {
                "total": ot,
                "success": osucc,
                "failed": ofail,
                "latency_sum_ms": olat,
                "latency_mean_ms": (olat / ot) if ot > 0 else 0.0,
            }

    return {
        "requests_total": tot,
        "requests_success": succ,
        "requests_failed": fail,
        "latency_sum_ms": lat_sum,
        "latency_mean_ms": (lat_sum / tot) if tot > 0 else 0.0,
        "success_rate_pct": (succ / tot * 100.0) if tot > 0 else 0.0,
        "operations": ops_delta,
    }


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
