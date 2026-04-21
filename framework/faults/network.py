"""Phase 2 placeholder: network chaos (latency, loss, partition).

Implement fault types in this module and register them; see ``framework/README.md``.
"""

from __future__ import annotations

from typing import Any

from framework.faults.base import Fault, FaultSpec
from framework.faults.registry import register

_EXTENSION_DOC = "framework/README.md (Phase 2 network chaos)"


@register("network_chaos")
class NetworkFault(Fault):
    """Not implemented in Phase 1 — reserved extension point for tc/NetworkPolicy chaos."""

    def apply(self) -> dict[str, Any]:
        raise NotImplementedError(
            "Network chaos is Phase 2. See "
            + _EXTENSION_DOC
            + " for how to add latency, loss, or partition faults."
        )

    def revert(self, state: dict[str, Any]) -> None:
        raise NotImplementedError(
            "Network chaos is Phase 2. See " + _EXTENSION_DOC + "."
        )


__all__ = ["NetworkFault"]
