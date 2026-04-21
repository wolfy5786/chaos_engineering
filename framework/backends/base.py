"""Execution backend contract for fault injection."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Target:
    """A workload addressable by backend verbs (typically a Pod)."""

    namespace: str
    name: str


@dataclass(frozen=True)
class ManifestResource:
    """One API object applied to the cluster."""

    api_version: str
    kind: str
    name: str
    namespace: str  # Use "" for cluster-scoped resources.


@dataclass(frozen=True)
class ManifestRef:
    """Handle for undoing ``apply_manifest`` (may include multiple objects)."""

    resources: tuple[ManifestResource, ...]


@dataclass(frozen=True)
class ExecResult:
    """Result of ``exec_in_pod``."""

    exit_code: int
    stdout: str
    stderr: str


class BackendError(RuntimeError):
    """Raised when a backend command fails or returns invalid output."""

    def __init__(
        self,
        message: str,
        *,
        returncode: int | None = None,
        stderr: str = "",
        stdout: str = "",
        command: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = stdout
        self.command = command


class ExecutionBackend(ABC):
    """Minimal verb set used by fault implementations (no direct kubectl imports in faults)."""

    @abstractmethod
    def list_targets(self, namespace: str, label_selector: str) -> list[Target]:
        """Return pods matching ``label_selector`` in ``namespace``."""

    @abstractmethod
    def delete_pod(self, target: Target) -> None:
        """Delete a pod by name."""

    @abstractmethod
    def exec_in_pod(
        self,
        target: Target,
        argv: list[str],
        *,
        container: str | None = None,
        timeout: float | None = None,
    ) -> ExecResult:
        """Run ``argv`` in the pod (optionally a specific container)."""

    @abstractmethod
    def apply_manifest(self, yaml_str: str) -> ManifestRef:
        """Apply YAML from memory; return refs for ``delete_manifest``."""

    @abstractmethod
    def delete_manifest(self, ref: ManifestRef) -> None:
        """Delete resources previously applied."""

    @abstractmethod
    def copy_into_pod(self, target: Target, local_path: str, remote_path: str) -> None:
        """Copy a local file or directory into the pod filesystem."""

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}()"


__all__ = [
    "BackendError",
    "ExecResult",
    "ExecutionBackend",
    "ManifestRef",
    "ManifestResource",
    "Target",
]
