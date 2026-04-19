# Repository structure

This document describes a **logical layout** for the chaos engineering project. It aligns with the architecture in [`implementation_guide.md`](implementation_guide.md) and supports **Phase 1** delivery with clear places for **Phase 2** (security monitoring, security assertions, network chaos). Adjust names to match your actual repository as it grows.

```
.
├── README.md
├── REPOSITORY_STRUCTURE.md
├── implementation_guide.md
├── requirements.txt                 # Python dependencies (or pyproject.toml)
├── docker-compose.yml               # Local / lab stack: SUT + optional observability
├── .env.example                     # Non-secret defaults for local runs
│
├── framework/                       # Control plane + analysis (core library)
│   ├── __init__.py
│   ├── orchestrator.py              # Scenario lifecycle: baseline → inject → recover → analyze
│   ├── fault_injector.py            # Fault types: compute, process, data; Phase 2: network module
│   ├── workload_generator.py        # Stress / realistic client traffic
│   ├── log_aggregator.py            # Log collection from targets
│   ├── traffic_monitor.py           # Request/response or service-mesh style capture
│   ├── assertions/                  # Phase 2-friendly: split by domain
│   │   ├── __init__.py
│   │   ├── base.py                  # Shared assertion interfaces
│   │   ├── resilience.py            # Phase 1: SLO / availability style checks
│   │   └── security.py              # Phase 2: security property checks (optional import)
│   ├── report_generator.py          # HTML + JSON (+ export for analytics)
│   └── plugins/                     # Optional: third-party or team-specific extensions
│       └── .gitkeep
│
├── scenarios/                       # Declarative experiments (YAML)
│   ├── README.md                    # Optional: scenario authoring notes
│   ├── examples/                    # Starter scenarios
│   └── production-like/             # Optional: heavier or longer runs
│
├── integrations/                    # Easy K8s and external tool hooks
│   ├── kubernetes/                  # Manifests, runbooks, Job templates
│   │   ├── README.md
│   │   └── examples/
│   └── ci/                          # GitHub Actions / GitLab CI snippets (optional)
│
├── services/                        # System under test (SUT) — demo / lab microservices
│   ├── api-gateway/
│   ├── auth-service/
│   ├── user-service/
│   ├── data-service/
│   └── log-service/                 # Or ELK stack piece; see implementation guide
│
├── tests/                           # Unit / integration tests for framework
│   ├── unit/
│   └── integration/
│
└── results/                         # Generated reports (gitignored)
    ├── .gitignore
    └── README.md                  # Optional: explain artifact layout
```

## Extension points (Phase 2)

| Location | Purpose |
|----------|---------|
| `framework/assertions/security.py` | Security property rules without changing orchestrator contracts. |
| `framework/fault_injector.py` (or `framework/faults/network.py`) | Network chaos (latency, loss, partition) as additional fault kinds. |
| `framework/log_aggregator.py` + `traffic_monitor.py` | Feeds for security monitoring and detection pipelines. |
| `integrations/kubernetes/` | Network policies, chaos experiments, or controllers that mirror local fault semantics. |

## Generated / local-only paths

- **`results/`** — Default output for HTML/JSON reports; should be listed in `.gitignore`.
- **Virtual environments** — e.g. `venv/` — not committed.
