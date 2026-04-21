"""Fault base types and Pydantic specs/handles."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from framework.backends.base import ExecutionBackend


class FaultTarget(BaseModel):
    """Label-based targeting; never hardcode pod or service names in scenarios."""

    model_config = ConfigDict(extra="forbid")

    namespace: str
    label_selector: str
    container: str | None = None


class FaultSpec(BaseModel):
    """YAML fault entry passed through the orchestrator; ``type`` selects the fault class."""

    model_config = ConfigDict(extra="allow")

    type: str
    target: FaultTarget = Field(..., description="Namespace and label selector for resolving pods")


class FaultHandle(BaseModel):
    """Opaque, JSON-serializable state for ``remove``/cleanup after inject."""

    model_config = ConfigDict(extra="forbid")

    type: str
    state: dict[str, Any]


class Fault(ABC):
    """Single fault type; implemented classes self-register via ``register``."""

    def __init__(self, backend: ExecutionBackend, spec: FaultSpec) -> None:
        self._backend = backend
        self._spec = spec

    @property
    def spec(self) -> FaultSpec:
        return self._spec

    @abstractmethod
    def apply(self) -> dict[str, Any]:
        """Run the fault; return JSON-serializable state stored on the handle."""

    @abstractmethod
    def revert(self, state: dict[str, Any]) -> None:
        """Undo the fault using only backend verbs."""


__all__ = ["Fault", "FaultHandle", "FaultSpec", "FaultTarget"]
