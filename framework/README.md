# Framework — fault injector

Phase 1 faults target Kubernetes workloads via **label selectors** (no hardcoded pod names, no imports from `dummy_test/`). The orchestrator passes YAML scenario fragments; the **FaultInjector** facade validates specs and delegates to registered fault classes.

## Architecture

| Piece | Role |
|--------|------|
| `FaultInjector` | `inject(spec)` → `FaultHandle`; `remove(handle)` runs `revert` |
| `framework.faults.*` | One class per `type` string, registered with `@register("...")` |
| `ExecutionBackend` | `kubectl`, `null` (tests), future `docker` / Python client |
| `framework/config.py` | `CHAOS_BACKEND` env (`kubectl` default, `null` for unit tests) |

## YAML fault spec

Each fault is a mapping:

- **`type`** — registered name: `pod_kill`, `pod_pause`, `network_chaos` (stub).
- **`target`** — `{ namespace, label_selector, container? }`
- **Extra keys** — interpreted by the fault (e.g. `delay_seconds`).

Example ([`scenarios/examples/pod_kill_auth.yaml`](../scenarios/examples/pod_kill_auth.yaml)):

```yaml
faults:
  - type: pod_kill
    target:
      namespace: dummy-test
      label_selector: app.kubernetes.io/component=auth
```

## CLI

From the repository root (with `kubectl` and kubeconfig for your cluster):

```bash
python -m framework.fault_injector inject --spec scenarios/examples/pod_kill_auth.yaml
python -m framework.fault_injector remove --handle handle.json
```

`inject` prints a **FaultHandle** JSON; pass it to `remove` for revert (e.g. `pod_pause` sends SIGCONT).

## Orchestrator hooks

- `fault_injector.inject_scenario(scenario)` — applies each entry in `scenario["faults"]`.
- `fault_injector.recover_scenario(scenario)` — reverts in reverse order.

Legacy aliases: `inject` / `recover` match the names used by `framework.orchestrator`.

## Extending backends

1. Subclass `framework.backends.base.ExecutionBackend`.
2. Register the factory in `framework/config.py` (`CHAOS_BACKEND`).

Only `get_execution_backend()` should construct backends so faults stay decoupled.

## Extending fault types

1. Subclass `framework.faults.base.Fault` (`apply` / `revert`).
2. Decorate with `@register("your_type")` in a module under `framework/faults/`.
3. Import that module from `framework/faults/__init__.py` so registration runs at import time.

## Phase 2 network chaos

`network_chaos` is registered but **`apply` raises `NotImplementedError`** until latency/loss/partition logic is added (typically `tc`, NetworkPolicy, or a chaos controller). Implement in [`faults/network.py`](faults/network.py) and keep the same `Fault` / backend contract.

## Tests

- Unit: `pytest tests/unit/`
- Integration (real cluster): `CHAOS_IT=1 pytest tests/integration/`
