"""Execution backends for fault injection (kubectl, null; docker and others later)."""

from framework.backends.kubectl import KubectlBackend
from framework.backends.null import NullBackend

__all__ = ["KubectlBackend", "NullBackend"]
