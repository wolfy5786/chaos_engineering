"""Construct a chaos execution backend from environment."""

from __future__ import annotations

import os

CHAOS_BACKEND_ENV = "CHAOS_BACKEND"
_DEFAULT_BACKEND = "kubectl"


def get_execution_backend():
    """Return the backend selected by ``CHAOS_BACKEND`` (default: ``kubectl``).

    Supported values: ``kubectl``, ``null``. Other values raise ``ValueError``.
    """
    name = os.environ.get(CHAOS_BACKEND_ENV, _DEFAULT_BACKEND).strip().lower()
    if name == _DEFAULT_BACKEND:
        from framework.backends.kubectl import KubectlBackend as _KubectlBackend

        return _KubectlBackend()
    if name == "null":
        from framework.backends.null import NullBackend as _NullBackend

        return _NullBackend()
    raise ValueError(
        f"Unknown {CHAOS_BACKEND_ENV}={name!r}; expected {_DEFAULT_BACKEND!r} or 'null'"
    )
