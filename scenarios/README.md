# Scenarios

Declarative experiment YAML consumed by the orchestrator and by the fault injector CLI.

- **`examples/`** — starter faults targeting the `dummy-test` namespace (see `dummy_test/README.md` for the SUT).
- Each fault entry uses **label selectors** under `target` — no pod names required.

Authoring notes: see [`framework/README.md`](../framework/README.md).
