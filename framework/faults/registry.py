"""Fault type registry (decorator + lookup)."""

from __future__ import annotations

from framework.faults.base import Fault

_REGISTRY: dict[str, type[Fault]] = {}


def register(name: str):
    """Decorator: ``@register("pod_kill") class PodKillFault(Fault): ...``."""

    def _decorator(cls: type[Fault]) -> type[Fault]:
        if name in _REGISTRY:
            raise ValueError(f"Duplicate fault registration for type {name!r}")
        _REGISTRY[name] = cls
        return cls

    return _decorator


def lookup(name: str) -> type[Fault]:
    """Return the fault class for ``name`` or raise ``KeyError``."""
    if name not in _REGISTRY:
        raise KeyError(f"Unknown fault type: {name!r}")
    return _REGISTRY[name]


def registered_names() -> frozenset[str]:
    """All registered fault type names (for tests)."""
    return frozenset(_REGISTRY.keys())


__all__ = ["lookup", "register", "registered_names"]
