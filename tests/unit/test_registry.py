"""Fault registry: lookup, duplicate registration, names."""

from __future__ import annotations

import uuid

import pytest

from framework.faults.base import Fault
from framework.faults.registry import lookup, registered_names, register


def test_lookup_pod_kill() -> None:
    cls = lookup("pod_kill")
    assert issubclass(cls, Fault)


def test_lookup_unknown_raises() -> None:
    with pytest.raises(KeyError, match="Unknown fault type"):
        lookup("not_a_real_fault_type_xyz")


def test_registered_names_includes_compute_and_network_stub() -> None:
    names = registered_names()
    assert "pod_kill" in names
    assert "pod_pause" in names
    assert "single_pod_kill" in names
    assert "multi_pod_kill" in names
    assert "multi_service_pod_kill" in names
    assert "network_chaos" in names


def test_duplicate_registration_raises() -> None:
    uid = "dup_test_" + uuid.uuid4().hex[:12]

    @register(uid)
    class _UniqueFault(Fault):
        def apply(self):
            return {}

        def revert(self, state):
            pass

    assert lookup(uid) is _UniqueFault

    with pytest.raises(ValueError, match="Duplicate fault registration"):

        @register(uid)
        class _Dup(Fault):
            def apply(self):
                return {}

            def revert(self, state):
                pass
