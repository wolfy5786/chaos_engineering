"""Compute faults against NullBackend."""

from __future__ import annotations

import pytest

from framework.backends.base import Target
from framework.backends.null import NullBackend
from framework.fault_injector import FaultInjector
from framework.faults.base import FaultSpec, FaultTarget


def test_pod_kill_sequence() -> None:
    tg = Target(namespace="dummy-test", name="auth-abc123")
    backend = NullBackend(list_targets_result=[tg])
    inj = FaultInjector(backend=backend)
    handle = inj.inject(
        {
            "type": "pod_kill",
            "target": {
                "namespace": "dummy-test",
                "label_selector": "app.kubernetes.io/component=auth",
            },
        }
    )
    assert handle.type == "pod_kill"
    assert handle.state.get("deleted_pods")
    methods = [c[0] for c in backend.calls]
    assert methods == ["list_targets", "delete_pod"]
    inj.remove(handle)


def test_pod_kill_no_targets_raises() -> None:
    backend = NullBackend(list_targets_result=[])
    inj = FaultInjector(backend=backend)
    with pytest.raises(RuntimeError, match="no pods matched"):
        inj.inject(
            {
                "type": "pod_kill",
                "target": {
                    "namespace": "dummy-test",
                    "label_selector": "app=nothing",
                },
            }
        )


def test_pod_pause_sequence() -> None:
    tg = Target(namespace="dummy-test", name="gw-xyz")
    backend = NullBackend(list_targets_result=[tg])
    inj = FaultInjector(backend=backend)
    handle = inj.inject(
        {
            "type": "pod_pause",
            "target": {
                "namespace": "dummy-test",
                "label_selector": "app.kubernetes.io/component=gateway",
            },
        }
    )
    assert handle.type == "pod_pause"
    assert "paused" in handle.state
    methods = [c[0] for c in backend.calls]
    assert methods == ["list_targets", "exec_in_pod"]
    inj.remove(handle)
    # revert adds exec_in_pod for SIGCONT
    assert [c[0] for c in backend.calls].count("exec_in_pod") == 2
