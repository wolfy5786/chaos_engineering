"""Unit tests for framework.workload_generator endpoint parsing and requests."""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from framework import workload_generator as wg


def test_parse_endpoint_short_form_get() -> None:
    ep = wg._parse_endpoint_spec("health", "GET /health")
    assert ep == {
        "method": "GET",
        "path": "/health",
        "body": None,
        "headers": None,
        "params": None,
    }


def test_parse_endpoint_short_form_post_defaults_to_no_body() -> None:
    ep = wg._parse_endpoint_spec("login", "POST /auth/login")
    assert ep["method"] == "POST"
    assert ep["path"] == "/auth/login"
    assert ep["body"] is None


def test_parse_endpoint_full_form_body_and_env_substitution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOGIN_EMAIL", "alice@example.com")
    monkeypatch.setenv("LOGIN_PASSWORD", "s3cr3t")
    ep = wg._parse_endpoint_spec(
        "login",
        {
            "method": "post",
            "path": "/auth/login",
            "body": {
                "email": "${LOGIN_EMAIL}",
                "password": "${LOGIN_PASSWORD}",
            },
            "headers": {"X-Test": "run-${RUN_ID:local}"},
        },
    )
    assert ep["method"] == "POST"
    assert ep["path"] == "/auth/login"
    assert ep["body"] == {"email": "alice@example.com", "password": "s3cr3t"}
    assert ep["headers"] == {"X-Test": "run-local"}


def test_parse_endpoint_env_substitution_missing_without_default_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LOGIN_EMAIL", raising=False)
    ep = wg._parse_endpoint_spec(
        "login",
        {"method": "POST", "path": "/auth/login", "body": {"email": "${LOGIN_EMAIL}"}},
    )
    assert ep["body"] == {"email": ""}


def test_parse_endpoint_missing_path_raises() -> None:
    with pytest.raises(ValueError, match="'path' is required"):
        wg._parse_endpoint_spec("bad", {"method": "POST"})


def test_parse_endpoint_rejects_non_string_non_mapping() -> None:
    with pytest.raises(TypeError, match="expected string or mapping"):
        wg._parse_endpoint_spec("bad", 42)


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _RecordingSession:
    """Session stub that records (method, url, kwargs) for each request."""

    def __init__(self, status_code: int = 200) -> None:
        self.headers: dict[str, str] = {}
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self._status_code = status_code

    def request(self, method: str, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append((method, url, kwargs))
        return _FakeResponse(self._status_code)

    def close(self) -> None:
        pass


def _run_one_iteration(workload_cfg: dict[str, Any], session: _RecordingSession) -> None:
    """Spin up one worker, let it issue >=1 request, then stop it."""
    wg._reset_state()
    assert wg._stop_event is not None
    stop = wg._stop_event

    original_build = wg._build_session
    wg._build_session = lambda _cfg: session  # type: ignore[assignment]
    try:
        t = threading.Thread(
            target=wg._worker_loop,
            args=(workload_cfg, stop, 0.0, 0),
            daemon=True,
        )
        t.start()
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not session.calls:
            time.sleep(0.01)
        stop.set()
        t.join(timeout=2.0)
    finally:
        wg._build_session = original_build  # type: ignore[assignment]


def test_worker_sends_json_body_for_login(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOGIN_EMAIL", "alice@example.com")
    monkeypatch.setenv("LOGIN_PASSWORD", "s3cr3t")
    session = _RecordingSession(status_code=200)
    workload_cfg = {
        "rps": 50,
        "num_workers": 1,
        "targets": {
            "base_url": "http://localhost:8000",
            "endpoints": {
                "login": {
                    "method": "POST",
                    "path": "/auth/login",
                    "body": {
                        "email": "${LOGIN_EMAIL}",
                        "password": "${LOGIN_PASSWORD}",
                    },
                },
            },
        },
        "operations": ["login"],
    }
    _run_one_iteration(workload_cfg, session)

    assert session.calls, "worker did not issue any request"
    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url == "http://localhost:8000/auth/login"
    assert kwargs.get("json") == {
        "email": "alice@example.com",
        "password": "s3cr3t",
    }


def test_worker_records_status_code_in_per_op_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOGIN_EMAIL", "u@x")
    monkeypatch.setenv("LOGIN_PASSWORD", "p")
    session = _RecordingSession(status_code=200)
    workload_cfg = {
        "rps": 50,
        "num_workers": 1,
        "targets": {
            "base_url": "http://localhost:8000",
            "endpoints": {
                "login": {
                    "method": "POST",
                    "path": "/auth/login",
                    "body": {"email": "${LOGIN_EMAIL}", "password": "${LOGIN_PASSWORD}"},
                }
            },
        },
        "operations": ["login"],
    }
    _run_one_iteration(workload_cfg, session)

    snapshot = wg.get_metrics()
    login_stats = snapshot["operations"]["login"]
    assert login_stats["total"] >= 1
    assert login_stats["success"] >= 1
    assert login_stats["status_counts"].get("200", 0) >= 1


def test_worker_round_robin_hits_every_op() -> None:
    session = _RecordingSession(status_code=200)
    workload_cfg = {
        "rps": 100,
        "num_workers": 1,
        "selection": "round_robin",
        "targets": {
            "base_url": "http://localhost:8000",
            "endpoints": {
                "a": "GET /a",
                "b": "GET /b",
                "c": "GET /c",
            },
        },
        "operations": ["a", "b", "c"],
    }

    wg._reset_state()
    assert wg._stop_event is not None
    stop = wg._stop_event

    original_build = wg._build_session
    wg._build_session = lambda _cfg: session  # type: ignore[assignment]
    try:
        t = threading.Thread(
            target=wg._worker_loop,
            args=(workload_cfg, stop, 0.0, 0),
            daemon=True,
        )
        t.start()
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and len(session.calls) < 6:
            time.sleep(0.01)
        stop.set()
        t.join(timeout=2.0)
    finally:
        wg._build_session = original_build  # type: ignore[assignment]

    paths = [url.rsplit("/", 1)[-1] for _m, url, _k in session.calls]
    assert set(paths[:3]) == {"a", "b", "c"}


def test_worker_keeps_cycling_after_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 500 status on /failing must not stop the worker from hitting /ok."""

    class _MixedSession(_RecordingSession):
        def request(self, method: str, url: str, **kwargs: Any) -> _FakeResponse:
            self.calls.append((method, url, kwargs))
            if url.endswith("/failing"):
                return _FakeResponse(500)
            return _FakeResponse(200)

    session = _MixedSession()
    workload_cfg = {
        "rps": 100,
        "num_workers": 1,
        "selection": "round_robin",
        "targets": {
            "base_url": "http://localhost:8000",
            "endpoints": {"ok": "GET /ok", "failing": "GET /failing"},
        },
        "operations": ["ok", "failing"],
    }

    wg._reset_state()
    assert wg._stop_event is not None
    stop = wg._stop_event

    original_build = wg._build_session
    wg._build_session = lambda _cfg: session  # type: ignore[assignment]
    try:
        t = threading.Thread(
            target=wg._worker_loop,
            args=(workload_cfg, stop, 0.0, 0),
            daemon=True,
        )
        t.start()
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and len(session.calls) < 8:
            time.sleep(0.01)
        stop.set()
        t.join(timeout=2.0)
    finally:
        wg._build_session = original_build  # type: ignore[assignment]

    paths = [url.rsplit("/", 1)[-1] for _m, url, _k in session.calls]
    assert paths.count("ok") >= 2
    assert paths.count("failing") >= 2

    snapshot = wg.get_metrics()
    assert snapshot["operations"]["failing"]["failed"] >= 1
    assert snapshot["operations"]["ok"]["success"] >= 1
