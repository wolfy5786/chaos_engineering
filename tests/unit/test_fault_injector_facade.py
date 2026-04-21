"""FaultInjector inject/remove and scenario hooks."""

from __future__ import annotations

import pytest

from framework.backends.base import Target
from framework.backends.null import NullBackend
from framework import fault_injector as fi


def test_network_chaos_raises_not_implemented() -> None:
    with pytest.raises(NotImplementedError, match="Phase 2"):
        fi.FaultInjector(backend=NullBackend()).inject(
            {
                "type": "network_chaos",
                "target": {"namespace": "dummy-test", "label_selector": "app=gw"},
            }
        )


def test_inject_scenario_and_recover(monkeypatch) -> None:
    tg = Target(namespace="dummy-test", name="p1")
    backend = NullBackend(list_targets_result=[tg])

    def _get_backend():
        return backend

    monkeypatch.setattr("framework.fault_injector.get_execution_backend", _get_backend)
    fi.inject_scenario(
        {
            "faults": [
                {
                    "type": "pod_kill",
                    "target": {
                        "namespace": "dummy-test",
                        "label_selector": "app.kubernetes.io/component=auth",
                    },
                }
            ]
        }
    )
    assert len(fi._active_handles) == 1
    fi.recover_scenario({})
    assert fi._active_handles == []
