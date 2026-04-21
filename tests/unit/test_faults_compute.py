"""Compute faults against NullBackend."""

from __future__ import annotations

import pytest

from framework.backends.base import ExecResult, Target
from framework.backends.null import NullBackend
from framework.fault_injector import FaultInjector
from framework.faults.base import FaultSpec, FaultTarget
from framework.faults.compute import PodPauseFault


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


def test_single_pod_kill_picks_one() -> None:
    tgs = [
        Target(namespace="dummy-test", name=f"p-{i}")
        for i in range(3)
    ]
    backend = NullBackend(list_targets_result=tgs)
    inj = FaultInjector(backend=backend)
    handle = inj.inject(
        {
            "type": "single_pod_kill",
            "target": {
                "namespace": "dummy-test",
                "label_selector": "app.kubernetes.io/component=svc-b",
            },
        }
    )
    assert handle.type == "single_pod_kill"
    deleted = handle.state.get("deleted_pods") or []
    assert len(deleted) == 1
    assert [c[0] for c in backend.calls].count("delete_pod") == 1
    inj.remove(handle)


def test_single_pod_kill_no_targets_raises() -> None:
    backend = NullBackend(list_targets_result=[])
    inj = FaultInjector(backend=backend)
    with pytest.raises(RuntimeError, match="single_pod_kill: no pods matched"):
        inj.inject(
            {
                "type": "single_pod_kill",
                "target": {
                    "namespace": "dummy-test",
                    "label_selector": "app=nothing",
                },
            }
        )


def test_multi_pod_kill_count() -> None:
    tgs = [
        Target(namespace="dummy-test", name=f"sva-{i}")
        for i in range(5)
    ]
    backend = NullBackend(list_targets_result=tgs)
    inj = FaultInjector(backend=backend)
    handle = inj.inject(
        {
            "type": "multi_pod_kill",
            "target": {
                "namespace": "dummy-test",
                "label_selector": "app.kubernetes.io/component=svc-a",
            },
            "count": 3,
        }
    )
    assert handle.type == "multi_pod_kill"
    assert handle.state.get("applied") == 3
    assert len(handle.state.get("deleted_pods") or []) == 3
    assert [c[0] for c in backend.calls].count("delete_pod") == 3
    inj.remove(handle)


def test_multi_pod_kill_clamps_to_available() -> None:
    tgs = [
        Target(namespace="dummy-test", name=f"p-{i}")
        for i in range(3)
    ]
    backend = NullBackend(list_targets_result=tgs)
    inj = FaultInjector(backend=backend)
    handle = inj.inject(
        {
            "type": "multi_pod_kill",
            "target": {
                "namespace": "dummy-test",
                "label_selector": "app=svc",
            },
            "count": 100,
        }
    )
    assert handle.state.get("applied") == 3
    assert len(handle.state.get("deleted_pods") or []) == 3
    assert [c[0] for c in backend.calls].count("delete_pod") == 3
    inj.remove(handle)


def test_multi_pod_kill_no_targets_raises() -> None:
    backend = NullBackend(list_targets_result=[])
    inj = FaultInjector(backend=backend)
    with pytest.raises(RuntimeError, match="multi_pod_kill: no pods matched"):
        inj.inject(
            {
                "type": "multi_pod_kill",
                "target": {
                    "namespace": "dummy-test",
                    "label_selector": "app=nothing",
                },
                "count": 2,
            }
        )


def test_multi_pod_kill_invalid_count_raises() -> None:
    tg = Target(namespace="dummy-test", name="only-one")
    backend = NullBackend(list_targets_result=[tg])
    inj = FaultInjector(backend=backend)
    with pytest.raises(RuntimeError, match="count must be >= 1"):
        inj.inject(
            {
                "type": "multi_pod_kill",
                "target": {
                    "namespace": "dummy-test",
                    "label_selector": "app=x",
                },
                "count": 0,
            }
        )


def test_multi_service_pod_kill_uses_target_selector_list() -> None:
    class _SelectorMappedBackend(NullBackend):
        def __init__(self) -> None:
            super().__init__()
            self._targets_by_selector = {
                "app.kubernetes.io/component=auth": [
                    Target(namespace="dummy-test", name="auth-0"),
                    Target(namespace="dummy-test", name="auth-1"),
                ],
                "app.kubernetes.io/component=svc-a": [
                    Target(namespace="dummy-test", name="svc-a-0"),
                ],
            }

        def list_targets(self, namespace: str, label_selector: str) -> list[Target]:
            self._record("list_targets", namespace, label_selector)
            return list(self._targets_by_selector.get(label_selector, []))

    backend = _SelectorMappedBackend()
    inj = FaultInjector(backend=backend)
    handle = inj.inject(
        {
            "type": "multi_service_pod_kill",
            "target": {
                "namespace": "dummy-test",
                "label_selector": "",
            },
            "targets": [
                "app.kubernetes.io/component=auth",
                "app.kubernetes.io/component=svc-a",
            ],
        }
    )
    assert handle.type == "multi_service_pod_kill"
    assert handle.state.get("applied") == 3
    assert len(handle.state.get("deleted_pods") or []) == 3
    assert [c[0] for c in backend.calls].count("list_targets") == 2
    assert [c[0] for c in backend.calls].count("delete_pod") == 3
    inj.remove(handle)


def test_multi_service_pod_kill_requires_targets_list() -> None:
    backend = NullBackend(
        list_targets_result=[Target(namespace="dummy-test", name="any-0")]
    )
    inj = FaultInjector(backend=backend)
    with pytest.raises(RuntimeError, match="targets must be a non-empty list of strings"):
        inj.inject(
            {
                "type": "multi_service_pod_kill",
                "target": {
                    "namespace": "dummy-test",
                    "label_selector": "",
                },
            }
        )


def test_multi_service_pod_kill_raises_for_selector_with_no_match() -> None:
    backend = NullBackend(list_targets_result=[])
    inj = FaultInjector(backend=backend)
    with pytest.raises(RuntimeError, match="no pods matched selector"):
        inj.inject(
            {
                "type": "multi_service_pod_kill",
                "target": {
                    "namespace": "dummy-test",
                    "label_selector": "",
                },
                "targets": ["app.kubernetes.io/component=missing"],
            }
        )


class _ExecResultBackend(NullBackend):
    """NullBackend variant that returns a scripted ExecResult from ``exec_in_pod``."""

    def __init__(self, *, exec_result: ExecResult, list_targets_result=None) -> None:
        super().__init__(list_targets_result=list_targets_result)
        self._exec_result = exec_result

    def exec_in_pod(self, target, argv, *, container=None, timeout=None):
        self._record("exec_in_pod", target, argv, container=container, timeout=timeout)
        return self._exec_result


def test_pod_pause_revert_tolerates_container_not_found(caplog) -> None:
    # Simulate kubelet having restarted the paused container: SIGCONT now fails
    # with exit 1 and the canonical "container not found" stderr. revert()
    # must log a warning and return without raising.
    state = {
        "paused": [
            {
                "namespace": "dummy-test",
                "name": "gateway-854dd66b8b-xqfc9",
                "container": None,
            }
        ]
    }
    backend = _ExecResultBackend(
        exec_result=ExecResult(
            exit_code=1,
            stdout="",
            stderr=(
                "error: Internal error occurred: unable to upgrade connection: "
                'container not found ("gateway")\n'
            ),
        ),
    )
    spec = FaultSpec(
        type="pod_pause",
        target=FaultTarget(namespace="_", label_selector=""),
    )
    fault = PodPauseFault(backend, spec)

    with caplog.at_level("WARNING", logger="framework.faults.compute"):
        fault.revert(state)

    assert any("SIGCONT skipped" in r.message for r in caplog.records)


def test_pod_pause_revert_raises_on_real_error() -> None:
    # A non-benign stderr (e.g. permission denied) must still raise.
    state = {
        "paused": [
            {"namespace": "dummy-test", "name": "gateway-abc", "container": None}
        ]
    }
    backend = _ExecResultBackend(
        exec_result=ExecResult(
            exit_code=1,
            stdout="",
            stderr="error: forbidden: User cannot exec into pods",
        ),
    )
    spec = FaultSpec(
        type="pod_pause",
        target=FaultTarget(namespace="_", label_selector=""),
    )
    fault = PodPauseFault(backend, spec)

    with pytest.raises(RuntimeError, match="SIGCONT failed for 1 pod"):
        fault.revert(state)


def test_pod_pause_revert_continues_past_benign_and_aggregates_real() -> None:
    # First pod is already gone (benign), second pod has a real error.
    # revert() must attempt both and raise once with the real failure only.
    state = {
        "paused": [
            {"namespace": "ns", "name": "gone", "container": None},
            {"namespace": "ns", "name": "broken", "container": None},
        ]
    }

    class _Scripted(NullBackend):
        def __init__(self) -> None:
            super().__init__()
            self._seq = [
                ExecResult(exit_code=1, stdout="", stderr='container not found ("x")'),
                ExecResult(exit_code=1, stdout="", stderr="forbidden"),
            ]

        def exec_in_pod(self, target, argv, *, container=None, timeout=None):
            self._record("exec_in_pod", target, argv, container=container, timeout=timeout)
            return self._seq.pop(0)

    backend = _Scripted()
    spec = FaultSpec(
        type="pod_pause",
        target=FaultTarget(namespace="_", label_selector=""),
    )
    fault = PodPauseFault(backend, spec)

    with pytest.raises(RuntimeError) as ei:
        fault.revert(state)
    msg = str(ei.value)
    assert "ns/broken" in msg
    assert "ns/gone" not in msg
    # Both pods should have been attempted.
    assert [c[0] for c in backend.calls].count("exec_in_pod") == 2
