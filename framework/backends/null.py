"""No-op execution backend that records calls for unit tests."""

from __future__ import annotations

from typing import Any

from framework.backends.base import (
    ExecResult,
    ExecutionBackend,
    ManifestRef,
    ManifestResource,
    Target,
)


class NullBackend(ExecutionBackend):
    """Records each backend verb invocation; returns safe defaults."""

    def __init__(self, *, list_targets_result: list[Target] | None = None) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self._list_targets_result: list[Target] = list(list_targets_result or [])

    def list_targets(self, namespace: str, label_selector: str) -> list[Target]:
        self._record("list_targets", namespace, label_selector)
        return list(self._list_targets_result)

    def delete_pod(self, target: Target) -> None:
        self._record("delete_pod", target)

    def exec_in_pod(
        self,
        target: Target,
        argv: list[str],
        *,
        container: str | None = None,
        timeout: float | None = None,
    ) -> ExecResult:
        self._record(
            "exec_in_pod",
            target,
            argv,
            container=container,
            timeout=timeout,
        )
        return ExecResult(exit_code=0, stdout="", stderr="")

    def apply_manifest(self, yaml_str: str) -> ManifestRef:
        self._record("apply_manifest", yaml_str)
        return ManifestRef(
            resources=(
                ManifestResource(
                    api_version="v1",
                    kind="ConfigMap",
                    name="null-placeholder",
                    namespace="default",
                ),
            )
        )

    def delete_manifest(self, ref: ManifestRef) -> None:
        self._record("delete_manifest", ref)

    def copy_into_pod(self, target: Target, local_path: str, remote_path: str) -> None:
        self._record("copy_into_pod", target, local_path, remote_path)

    def _record(self, method: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((method, args, kwargs))

    def clear(self) -> None:
        """Remove recorded calls (handy in tests)."""
        self.calls.clear()


__all__ = ["NullBackend"]
