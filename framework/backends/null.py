"""No-op execution backend for tests (implementation pending)."""


class NullBackend:
    """Records or ignores operations; used when validating fault logic without a cluster."""

    def __repr__(self) -> str:
        return "NullBackend()"


__all__ = ["NullBackend"]
