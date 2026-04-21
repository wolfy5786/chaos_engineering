"""Compute-style faults: pod lifecycle (kill, pause)."""

from __future__ import annotations

import time
from typing import Any

from framework.backends.base import Target
from framework.faults.base import Fault, FaultSpec
from framework.faults.registry import register


def _spec_extras(spec: FaultSpec) -> dict[str, Any]:
    return spec.model_dump(mode="python")


@register("pod_kill")
class PodKillFault(Fault):
    """Delete all pods matching the label selector (controller recreates them)."""

    def apply(self) -> dict[str, Any]:
        extra = _spec_extras(self._spec)
        delay = float(extra.get("delay_seconds") or 0)
        if delay > 0:
            time.sleep(delay)
        ns = self._spec.target.namespace
        sel = self._spec.target.label_selector
        targets = self._backend.list_targets(ns, sel)
        if not targets:
            raise RuntimeError(
                f"pod_kill: no pods matched selector {sel!r} in namespace {ns!r}"
            )
        deleted: list[dict[str, str]] = []
        for tg in targets:
            self._backend.delete_pod(tg)
            deleted.append({"namespace": tg.namespace, "name": tg.name})
        return {"deleted_pods": deleted}

    def revert(self, state: dict[str, Any]) -> None:
        # Workload controllers recreate pods; nothing to restore in-cluster.
        pass


@register("pod_pause")
class PodPauseFault(Fault):
    """Pause container PID 1 via SIGSTOP; resume with SIGCONT on revert."""

    _STOP_ARGV = ["/bin/sh", "-c", "kill -STOP 1"]
    _CONT_ARGV = ["/bin/sh", "-c", "kill -CONT 1"]

    def apply(self) -> dict[str, Any]:
        extra = _spec_extras(self._spec)
        delay = float(extra.get("delay_seconds") or 0)
        if delay > 0:
            time.sleep(delay)
        ns = self._spec.target.namespace
        sel = self._spec.target.label_selector
        container = self._spec.target.container
        targets = self._backend.list_targets(ns, sel)
        if not targets:
            raise RuntimeError(
                f"pod_pause: no pods matched selector {sel!r} in namespace {ns!r}"
            )
        paused: list[dict[str, str | None]] = []
        for tg in targets:
            result = self._backend.exec_in_pod(
                tg,
                self._STOP_ARGV,
                container=container,
                timeout=60.0,
            )
            if result.exit_code != 0:
                raise RuntimeError(
                    f"pod_pause: SIGSTOP failed for {tg.namespace}/{tg.name}: "
                    f"exit {result.exit_code} stderr={result.stderr!r}"
                )
            paused.append(
                {
                    "namespace": tg.namespace,
                    "name": tg.name,
                    "container": container,
                }
            )
        return {"paused": paused}

    def revert(self, state: dict[str, Any]) -> None:
        entries = state.get("paused") or []
        for entry in entries:
            ns = entry["namespace"]
            name = entry["name"]
            container = entry.get("container")
            tg = Target(namespace=str(ns), name=str(name))
            result = self._backend.exec_in_pod(
                tg,
                self._CONT_ARGV,
                container=container if container else None,
                timeout=60.0,
            )
            if result.exit_code != 0:
                raise RuntimeError(
                    f"pod_pause: SIGCONT failed for {tg.namespace}/{tg.name}: "
                    f"exit {result.exit_code} stderr={result.stderr!r}"
                )


__all__ = ["PodKillFault", "PodPauseFault"]
