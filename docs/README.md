# FinEdgar Documentation

This directory is the working map for the project. Start here when you need to
understand the system, run it locally, change a subsystem, or explain the
architecture to someone else.

## Start Here

| Document | Use it for |
|---|---|
| [Architecture](architecture.md) | System diagrams, request flow, data flow, deployment shape, and operational boundaries. |
| [Codebase Map](codebase-map.md) | What each source area owns, which files matter, and where to make changes. |
| [Data Pipeline](data_pipeline.md) | SEC inputs, generated artifacts, bootstrap/index commands, and validation checks. |
| [Docker Workflows](docker.md) | Local development, production-style local runs, jobs, evals, training containers, and database commands. |
| [Web App](../webapp/README.md) | FastAPI + React app behavior, auth flow, chat history, admin page, and local web workflow. |
| [Authentication](auth.md) | Password hashing, session cookies, token handling, same-origin checks, and public deployment requirements. |
| [Database](database.md) | Postgres schema, Alembic migrations, backup, restore, and reset workflow. |
| [Admin Interfaces](admin.md) | In-app operator dashboard and optional Dozzle log console. |
| [Model Fine-Tuning](model_finetuning.md) | Dataset preparation, training, export, Ollama registration, and eval workflow. |
| [Orchestrator](orchestrator.md) | Status of the older end-to-end runner and safer focused alternatives. |
| [Project Status](PROJECT_JOURNEY_AND_STATUS.md) | Current capability, known gaps, and near-term priorities. |

## Kubernetes Track

The Kubernetes docs are intentionally separated from the everyday Compose path.
Compose is the fastest way to develop. Kubernetes is the local platform lab.

| Document | Use it for |
|---|---|
| [Kubernetes Local Lab](kubernetes.md) | k3d quickstart, local image registry, Helm deploys, and common commands. |
| [Kubernetes Architecture](kubernetes-architecture.md) | Workload mapping, storage, routing, database, jobs, and scaling boundaries. |
| [Autoscaling And Load Testing](kubernetes-autoscaling.md) | HPA profile, k6 job, expected behavior, and demo checks. |
| [Observability](kubernetes-observability.md) | Prometheus, Grafana, Loki, Tempo, OpenTelemetry, app metrics, and traces. |
| [GPU Profile](kubernetes-gpu.md) | Optional NVIDIA path for Ollama and training workloads. |
| [Learning Roadmap](kubernetes-roadmap.md) | Suggested order for learning the platform pieces. |

## What Lives Outside `docs/`

| Path | Purpose |
|---|---|
| [README.md](../README.md) | Project overview, benchmark result, quick setup, and top-level workflows. |
| [docker/compose/README.md](../docker/compose/README.md) | Compact reference for Compose overlay files. |
| [webapp/README.md](../webapp/README.md) | Web-app-specific local workflow and user-facing behavior. |
| [charts/finedgar](../charts/finedgar) | Helm chart used by the local Kubernetes lab. |
| [scripts](../scripts) | Data, Docker, Kubernetes, evaluation, and training entry points. |
| [backend/tests](../backend/tests) | Regression tests for data pipeline, benchmark safety, auth, and chat history. |

## Documentation Rules

- Keep the top-level README short enough to orient a new reader.
- Put subsystem details in the matching document under `docs/`.
- Update [Codebase Map](codebase-map.md) when adding a new source directory,
  service, route, job, or long-running workflow.
- Update [Architecture](architecture.md) when a request path, data path, or
  deployment boundary changes.
- Prefer diagrams that match the code over diagrams that describe a future plan.
