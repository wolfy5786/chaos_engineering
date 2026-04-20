"""Fault injector facade: ``inject`` / ``remove`` with pluggable faults and backends.

Orchestrator compatibility: :func:`baseline`, :func:`inject`, :func:`recover` operate on a
full scenario mapping (see :func:`inject_scenario`).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Mapping

import yaml
from pydantic import ValidationError

# Ensure fault modules register with the registry
import framework.faults  # noqa: F401
from framework.backends.base import ExecutionBackend
from framework.config import get_execution_backend
from framework.faults.base import FaultHandle, FaultSpec, FaultTarget
from framework.faults.registry import lookup

logger = logging.getLogger(__name__)

# Handles applied by :func:`inject_scenario` for :func:`recover_scenario`
_active_handles: list[FaultHandle] = []


class FaultInjector:
    """Applies and reverts a single fault using the configured :class:`~framework.backends.base.ExecutionBackend`."""

    def __init__(self, backend: ExecutionBackend | None = None) -> None:
        self._backend = backend if backend is not None else get_execution_backend()

    def inject(self, spec: Mapping[str, Any] | FaultSpec) -> FaultHandle:
        """Validate ``spec``, run the matching fault's ``apply``, return a JSON-serializable handle."""
        if isinstance(spec, FaultSpec):
            fs = spec
        else:
            fs = FaultSpec.model_validate(dict(spec))
        cls = lookup(fs.type)
        fault = cls(self._backend, fs)
        state = fault.apply()
        return FaultHandle(type=fs.type, state=state)

    def remove(self, handle: FaultHandle) -> None:
        """Revert using the fault class's ``revert`` (spec is minimal; state carries undo data)."""
        cls = lookup(handle.type)
        minimal = FaultSpec(
            type=handle.type,
            target=FaultTarget(namespace="_", label_selector=""),
        )
        fault = cls(self._backend, minimal)
        fault.revert(handle.state)


def baseline(scenario: Mapping[str, Any]) -> None:
    """Establish no-fault baseline (logging hook for orchestrator)."""
    logger.info("fault_injector.baseline enter")
    logger.debug("fault_injector.baseline (no baseline faults applied)")
    logger.info("fault_injector.baseline exit")


def inject_scenario(scenario: Mapping[str, Any]) -> None:
    """Apply each entry in ``scenario['faults']`` and store handles for :func:`recover_scenario`."""
    global _active_handles
    _active_handles.clear()
    faults = scenario.get("faults") or []
    if not faults:
        logger.info("fault_injector.inject: no faults in scenario")
        return
    inj = FaultInjector()
    for i, fault_dict in enumerate(faults):
        if not isinstance(fault_dict, Mapping):
            raise TypeError(f"faults[{i}] must be a mapping")
        logger.info("fault_injector.inject: applying fault type=%s", fault_dict.get("type"))
        handle = inj.inject(fault_dict)
        _active_handles.append(handle)


def recover_scenario(scenario: Mapping[str, Any]) -> None:
    """Revert faults applied by :func:`inject_scenario` in reverse order."""
    global _active_handles
    inj = FaultInjector()
    for handle in reversed(_active_handles):
        try:
            inj.remove(handle)
        except Exception:
            logger.exception("fault_injector.recover: remove failed for type=%s", handle.type)
    _active_handles.clear()
    logger.info("fault_injector.recover exit")


# Backwards-compatible names used by ``framework.orchestrator``
def inject(scenario: Mapping[str, Any]) -> None:
    """Alias for :func:`inject_scenario`."""
    inject_scenario(scenario)


def recover(scenario: Mapping[str, Any]) -> None:
    """Alias for :func:`recover_scenario`."""
    recover_scenario(scenario)


def _load_one_fault_from_yaml(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        raise ValueError(f"Empty YAML: {path}")
    if isinstance(raw, dict) and "faults" in raw:
        faults = raw["faults"]
        if not faults:
            raise ValueError("YAML has empty 'faults' list")
        first = faults[0]
        if not isinstance(first, Mapping):
            raise TypeError("faults[0] must be a mapping")
        return dict(first)
    if isinstance(raw, dict) and "type" in raw and "target" in raw:
        return dict(raw)
    raise ValueError(
        "YAML must be either a fault object with 'type' and 'target', "
        "or a scenario object with non-empty 'faults'"
    )


def _fault_handle_from_json(path: Path) -> FaultHandle:
    data = json.loads(path.read_text(encoding="utf-8"))
    return FaultHandle.model_validate(data)


def main(argv: list[str] | None = None) -> int:
    """CLI: ``inject --spec <yaml>`` | ``remove --handle <json>``."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="Fault injector (single fault inject / remove)")
    sub = p.add_subparsers(dest="command", required=True)

    p_inj = sub.add_parser("inject", help="Apply one fault from YAML; print handle JSON on stdout")
    p_inj.add_argument(
        "--spec",
        type=Path,
        required=True,
        help="YAML file: one fault {type, target, ...} or scenario with faults[0] used",
    )

    p_rem = sub.add_parser("remove", help="Revert using a handle JSON from a previous inject")
    p_rem.add_argument(
        "--handle",
        type=Path,
        required=True,
        help="JSON file produced by inject (FaultHandle)",
    )

    args = p.parse_args(argv)
    try:
        if args.command == "inject":
            spec = _load_one_fault_from_yaml(args.spec)
            inj = FaultInjector()
            handle = inj.inject(spec)
            print(handle.model_dump_json(indent=2))
            return 0
        if args.command == "remove":
            handle = _fault_handle_from_json(args.handle)
            FaultInjector().remove(handle)
            print("ok", file=sys.stderr)
            return 0
    except (ValidationError, ValueError, KeyError, NotImplementedError) as e:
        logger.error("%s", e)
        print(f"error: {e}", file=sys.stderr)
        return 1
    except Exception:
        logger.exception("fault_injector CLI failed")
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
