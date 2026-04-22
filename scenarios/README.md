# Scenarios

Declarative experiment YAML consumed by the orchestrator and by the fault injector CLI.

- **`examples/`** — starter faults targeting the `dummy-test` namespace (see `dummy_test/README.md` for the SUT).
- **Phase 1 load / stress** (orchestrator pipeline, gateway workload):
  - [`phase1_load_steady.yaml`](phase1_load_steady.yaml) — fixed RPS, no faults.
  - [`phase1_load_burst.yaml`](phase1_load_burst.yaml) — `burst_pattern` only.
  - [`phase1_load_burst_and_fault.yaml`](phase1_load_burst_and_fault.yaml) — burst + `fault_rps` + pod faults (same sequence as `phase1_dummy_test.yaml`).
- Each fault entry uses **label selectors** under `target` — no pod names required.

**Knobs:** `workload` (`rps`, `burst_pattern`, `fault_rps`), `phases` (`baseline_duration_seconds`, `injection_duration_seconds`), `assertions.load` (thresholds). See comments in [`examples/skeleton.yaml`](examples/skeleton.yaml).

Authoring notes: see [`framework/README.md`](../framework/README.md).
