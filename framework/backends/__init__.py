"""Execution backends for fault injection (kubectl, null; docker and others later)."""

from framework.backends.base import (
    BackendError,
    ExecResult,
    ExecutionBackend,
    ManifestRef,
    ManifestResource,
    Target,
)
from framework.backends.kubectl import KubectlBackend
from framework.backends.null import NullBackend

__all__ = [
    "BackendError",
    "ExecResult",
    "ExecutionBackend",
    "KubectlBackend",
    "ManifestRef",
    "ManifestResource",
    "NullBackend",
    "Target",
]
