"""Pydantic validation for FaultSpec / FaultTarget."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from framework.faults.base import FaultSpec, FaultTarget


def test_fault_target_requires_namespace_and_selector() -> None:
    FaultTarget(namespace="ns", label_selector="app=web")


def test_fault_spec_missing_target_raises() -> None:
    with pytest.raises(ValidationError):
        FaultSpec.model_validate({"type": "pod_kill"})


def test_fault_spec_extra_fields_allowed() -> None:
    fs = FaultSpec.model_validate(
        {
            "type": "pod_kill",
            "target": {"namespace": "dummy-test", "label_selector": "app=auth"},
            "delay_seconds": 5,
        }
    )
    assert fs.type == "pod_kill"
    dumped = fs.model_dump()
    assert dumped.get("delay_seconds") == 5
