"""Compute-style faults: pod lifecycle (kill, pause)."""

from __future__ import annotations

import logging
import random
import time
from typing import Any

from framework.backends.base import BackendError, Target
from framework.faults.base import Fault, FaultSpec
from framework.faults.registry import register

logger = logging.getLogger(__name__)

# Substrings in kubectl/backend stderr that mean the target container or pod
# is already gone (e.g. kubelet restarted the container after a liveness-probe
# failure while it was SIGSTOPped). In those cases the pause effect is already
# cleared, so SIGCONT is a no-op and revert should continue instead of raise.
_BENIGN_REVERT_STDERR_MARKERS = (
    "container not found",
    "containernotfound",
    "not found",
    "is being terminated",
    "is not running",
    "unable to upgrade connection",
)


def _is_benign_revert_error(stderr: str) -> bool:
    s = (stderr or "").lower()
    return any(marker in s for marker in _BENIGN_REVERT_STDERR_MARKERS)


def _spec_extras(spec: FaultSpec) -> dict[str, Any]:
    return spec.model_dump(mode="python")


def _positive_count(extra: dict[str, Any], default: int, *, fault: str, field_name: str = "count") -> int:
    """Parse ``count`` from extras; must be >= 1 when set or defaulting."""
    raw = extra.get(field_name, default)
    try:
        n = int(raw)
    except (TypeError, ValueError) as e:
        raise RuntimeError(f"{fault}: {field_name} must be a positive integer") from e
    if n < 1:
        raise RuntimeError(f"{fault}: {field_name} must be >= 1, got {n!r}")
    return n


def _required_string_list(extra: dict[str, Any], *, fault: str, field_name: str) -> list[str]:
    """Parse a required non-empty list of non-empty strings from extras."""
    raw = extra.get(field_name)
    if not isinstance(raw, list) or not raw:
        raise RuntimeError(f"{fault}: {field_name} must be a non-empty list of strings")
    values: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise RuntimeError(
                f"{fault}: {field_name} entries must be non-empty strings"
            )
        values.append(item.strip())
    return values


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
        errors: list[str] = []
        for entry in entries:
            ns = entry["namespace"]
            name = entry["name"]
            container = entry.get("container")
            tg = Target(namespace=str(ns), name=str(name))
            try:
                result = self._backend.exec_in_pod(
                    tg,
                    self._CONT_ARGV,
                    container=container if container else None,
                    timeout=60.0,
                )
            except BackendError as e:
                # Backend itself failed (e.g. kubectl returned non-zero outside
                # of exec). If the target is already gone, treat as benign.
                if _is_benign_revert_error(e.stderr):
                    logger.warning(
                        "pod_pause: SIGCONT skipped for %s/%s; container/pod already gone "
                        "(likely restarted by kubelet after liveness-probe failure): %s",
                        tg.namespace,
                        tg.name,
                        (e.stderr or str(e)).strip(),
                    )
                    continue
                errors.append(
                    f"{tg.namespace}/{tg.name}: backend error: {e} stderr={e.stderr!r}"
                )
                continue
            if result.exit_code == 0:
                continue
            if _is_benign_revert_error(result.stderr):
                # kubelet already killed the paused container and restarted it,
                # so the pause effect is gone. Nothing to undo.
                logger.warning(
                    "pod_pause: SIGCONT skipped for %s/%s; container/pod already gone "
                    "(likely restarted by kubelet after liveness-probe failure): %s",
                    tg.namespace,
                    tg.name,
                    result.stderr.strip(),
                )
                continue
            errors.append(
                f"{tg.namespace}/{tg.name}: exit {result.exit_code} stderr={result.stderr!r}"
            )
        if errors:
            raise RuntimeError(
                "pod_pause: SIGCONT failed for "
                + str(len(errors))
                + " pod(s): "
                + "; ".join(errors)
            )


@register("single_pod_kill")
class SinglePodKillFault(Fault):
    """Delete one pod at random among those matching the label selector."""

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
                f"single_pod_kill: no pods matched selector {sel!r} in namespace {ns!r}"
            )
        chosen = random.choice(targets)
        self._backend.delete_pod(chosen)
        return {
            "deleted_pods": [
                {"namespace": chosen.namespace, "name": chosen.name},
            ]
        }

    def revert(self, state: dict[str, Any]) -> None:
        pass


@register("multi_pod_kill")
class MultiPodKillFault(Fault):
    """Delete ``count`` pods at random from one service (label selector)."""

    def apply(self) -> dict[str, Any]:
        extra = _spec_extras(self._spec)
        delay = float(extra.get("delay_seconds") or 0)
        if delay > 0:
            time.sleep(delay)
        count = _positive_count(extra, default=1, fault="multi_pod_kill")
        ns = self._spec.target.namespace
        sel = self._spec.target.label_selector
        targets = self._backend.list_targets(ns, sel)
        if not targets:
            raise RuntimeError(
                f"multi_pod_kill: no pods matched selector {sel!r} in namespace {ns!r}"
            )
        k = min(count, len(targets))
        chosen = random.sample(targets, k=k)
        deleted: list[dict[str, str]] = []
        for tg in chosen:
            self._backend.delete_pod(tg)
            deleted.append({"namespace": tg.namespace, "name": tg.name})
        return {"deleted_pods": deleted, "requested": count, "applied": k}

    def revert(self, state: dict[str, Any]) -> None:
        pass


@register("multi_service_pod_kill")
class MultiServicePodKillFault(Fault):
    """Delete pods matched by an explicit list of selectors across services."""

    def apply(self) -> dict[str, Any]:
        extra = _spec_extras(self._spec)
        delay = float(extra.get("delay_seconds") or 0)
        if delay > 0:
            time.sleep(delay)
        selectors = _required_string_list(
            extra,
            fault="multi_service_pod_kill",
            field_name="targets",
        )
        ns = self._spec.target.namespace
        unique_targets: dict[tuple[str, str], Target] = {}
        for sel in selectors:
            matched = self._backend.list_targets(ns, sel)
            if not matched:
                raise RuntimeError(
                    f"multi_service_pod_kill: no pods matched selector {sel!r} in namespace {ns!r}"
                )
            for tg in matched:
                unique_targets[(tg.namespace, tg.name)] = tg
        deleted: list[dict[str, str]] = []
        for tg in unique_targets.values():
            self._backend.delete_pod(tg)
            deleted.append({"namespace": tg.namespace, "name": tg.name})
        return {"deleted_pods": deleted, "requested_targets": selectors, "applied": len(deleted)}

    def revert(self, state: dict[str, Any]) -> None:
        pass


__all__ = [
    "MultiPodKillFault",
    "MultiServicePodKillFault",
    "PodKillFault",
    "PodPauseFault",
    "SinglePodKillFault",
]
