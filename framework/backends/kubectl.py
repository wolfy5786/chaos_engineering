"""kubectl-based execution backend (implementation pending)."""


class KubectlBackend:
    """Runs cluster operations via ``kubectl`` CLI."""

    def __repr__(self) -> str:
        return "KubectlBackend()"


__all__ = ["KubectlBackend"]
