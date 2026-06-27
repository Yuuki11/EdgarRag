# Codebase Map

This is the file-level map for FinEdgar. It is meant for maintenance: when you
need to change behavior, start by finding the owning module here, then follow
the tests listed near the end.

## Top-Level Layout

| Path | Responsibility |
|---|---|
| `backend/data/` | Core SEC data pipeline, XBRL calculations, retrieval, evaluation helpers, and the final answer pipeline. |
| `webapp/backend/` | FastAPI app, auth/session services, chat persistence, admin APIs, metrics, and web-facing schemas. |
| `webapp/frontend/` | React app for auth, company/year selection, chat, conversations, health, and admin status. |
| `model/training/` | Dataset preparation, QLoRA training, export, Ollama registration, and model verification. |
| `scripts/` | CLI entry points for data bootstrap, vector indexing, benchmark eval, Docker, and Kubernetes. |
| `docker/` | Runtime and training Dockerfiles plus Compose overlays. |
| `charts/finedgar/` | Helm chart for the local Kubernetes lab. |
| `deploy/k8s/` | Supporting Kubernetes manifests for k6 and observability dashboards. |
| `docs/` | System, deployment, auth, database, and operations documentation. |

## Core Data Pipeline

| File | Owns | Notes |
|---|---|---|
| `backend/data/__init__.py` | Lazy public exports for the data package. | Keeps imports light when optional ML dependencies are not installed. |
| `backend/data/models.py` | Shared dataclasses and section names. | `FilingChunk`, `CompanyInfo`, and `XBRLFact` are the common data shapes. |
| `backend/data/ticker_resolver.py` | Ticker to SEC CIK resolution. | Uses SEC ticker data, local cache, manual overrides, and rate limiting. |
| `backend/data/xbrl_fetcher.py` | SEC companyfacts download, cache, metric lookup, and fuzzy metric search. | This is the source of truth for raw structured financial facts. |
| `backend/data/xbrl_reasoning.py` | Deterministic financial calculations. | Ratios, changes, margins, cash conversion, derived metrics, and `compute_xbrl_answer`. |
| `backend/data/filing_downloader.py` | SEC filing discovery and download. | Handles recent and archived submission files, filing forms, cache paths, and document URLs. |
| `backend/data/section_parser.py` | 10-K section extraction. | Tries `sec-parser`, then falls back to regex/text boundary parsing. |
| `backend/data/document_parser.py` | Generic HTML/PDF text extraction. | Used for non-10-K documents and fallback parsing. |
| `backend/data/table_extractor.py` | HTML table to Markdown conversion. | Normalizes financial tables before chunking. |
| `backend/data/chunker.py` | Filing chunk creation. | Respects token budgets and preserves ticker/year/section metadata. |
| `backend/data/embeddings.py` | Sentence-transformers + FAISS index loading/search. | Dense retrieval path with metadata filtering. |
| `backend/data/retrieval.py` | Hierarchical retrieval over chunks. | Metadata filtering, section scoring, lexical ranking, neighbor expansion, and evidence curation. |
| `backend/data/reranker.py` | Optional cross-encoder reranking. | Keeps reranking isolated from the base retrieval path. |
| `backend/data/benchmarking.py` | FinanceBench planning and governance helpers. | Company resolution, metric extraction, operation classification, route choice, tuple keys, and split metadata. |
| `backend/data/answer_evaluator.py` | Scoring utilities. | Numeric parsing, official/internal answer scoring, and retrieval recall. |
| `backend/data/answer_pipeline.py` | End-to-end answering. | Builds the question plan, chooses XBRL/RAG/hybrid route, calls Ollama when needed, and returns `PipelineResult`. |

## Web Backend

| File | Owns | Notes |
|---|---|---|
| `webapp/backend/main.py` | FastAPI app assembly. | Registers middleware, metrics, OpenTelemetry, routers, CORS, and React static serving. |
| `webapp/backend/schemas.py` | API request/response models. | Shared contract between FastAPI and React. |
| `webapp/backend/db.py` | Async SQLAlchemy engine/session lifecycle. | Reads `DATABASE_URL` and exposes `get_db`. |
| `webapp/backend/db_models.py` | SQLAlchemy tables. | Users, sessions, tokens, conversations, messages, and auth events. |
| `webapp/backend/security.py` | Password/token/cookie/origin security helpers. | Normalizes email, hashes passwords/tokens, validates same-origin unsafe requests. |
| `webapp/backend/emailer.py` | Auth email transport. | Console mode for local work, SMTP mode for public deployments. |
| `webapp/backend/routes/auth.py` | Auth HTTP endpoints. | Register, verify, login, logout, current user, forgot password, and reset password. |
| `webapp/backend/routes/chat.py` | Authenticated chat endpoint. | Validates conversation ownership, runs the pipeline off the event loop, persists the turn. |
| `webapp/backend/routes/conversations.py` | Conversation CRUD and message history. | Enforces user ownership through service-layer queries. |
| `webapp/backend/routes/companies.py` | Available company/year catalog endpoint. | Reads local `data/companies.json` and artifact state. |
| `webapp/backend/routes/admin.py` | Operator overview endpoint. | Aggregates runtime, data artifact, database, auth, and Kubernetes metadata. |
| `webapp/backend/routes/health.py` | `/healthz`. | Reports Ollama reachability, active model, indexed companies, XBRL cache, and compute mode. |
| `webapp/backend/services/auth.py` | Auth business rules. | Creates users, sends tokens, verifies email, logs in/out, resets passwords, resolves current user. |
| `webapp/backend/services/conversations.py` | Chat history business rules. | Creates titles, lists conversations, persists user/assistant turns, soft-deletes conversations. |
| `webapp/backend/services/pipeline.py` | Adapter from data pipeline to web schema. | Converts `PipelineResult` to `ChatResponse`, citations, and XBRL evidence. |
| `webapp/backend/services/companies.py` | Company catalog loading. | Produces `CompanyYears` records for the frontend. |
| `webapp/backend/migrations/` | Alembic environment and migration scripts. | Keep migrations in step with `db_models.py`. |

## Web Frontend

| File | Owns | Notes |
|---|---|---|
| `webapp/frontend/src/main.tsx` | React entry point. | Mounts the app. |
| `webapp/frontend/src/App.tsx` | Main application state. | Auth state, route mode, selected company/year, conversations, chat turns, and admin view switching. |
| `webapp/frontend/src/api.ts` | Browser API client and TypeScript types. | Mirrors FastAPI schemas and centralizes fetch behavior. |
| `webapp/frontend/src/components/AuthScreen.tsx` | Login/register/verify/reset UI. | Handles token URLs and auth form modes. |
| `webapp/frontend/src/components/Chat.tsx` | Question form and chat layout. | Sends user questions and renders empty state. |
| `webapp/frontend/src/components/Message.tsx` | Answer rendering. | Shows route chips, citations, XBRL evidence, latency, and errors. |
| `webapp/frontend/src/components/CompanyPicker.tsx` | Company/year selectors. | Uses company catalog returned by FastAPI. |
| `webapp/frontend/src/components/ConversationSidebar.tsx` | Conversation list and actions. | Create, rename, select, and delete conversations. |
| `webapp/frontend/src/components/AdminDashboard.tsx` | Operator dashboard. | Renders admin metrics, data artifact state, runtime metadata, and auth events. |
| `webapp/frontend/src/components/HealthBadge.tsx` | Compact health status. | Shows API/model/index status in the header. |
| `webapp/frontend/src/styles.css` | Application styling. | Shared layout, forms, chat, sidebar, admin, and responsive behavior. |

## Training And Model Export

| File | Owns | Notes |
|---|---|---|
| `model/training/prepare_data.py` | Training dataset construction and validation. | Builds records from ConvFinQA, phrasebank, XBRL QA, and filing-diff summaries while guarding benchmark leakage. |
| `model/training/bootstrap_diffs.py` | Draft filing-diff examples. | Uses a local teacher model to prepare reviewable examples. |
| `model/training/train.py` | QLoRA fine-tuning. | Loads config, model, tokenizer, dataset, collator, and trainer. |
| `model/training/export.py` | LoRA merge/export and Modelfile generation. | Produces GGUF artifacts and Ollama registration helpers. |
| `model/training/verify_model.py` | Smoke checks for an Ollama model. | Sends representative prompts and reports whether the model behaves plausibly. |
| `model/configs/qlora_e4b.yaml` | Active training configuration. | Historical filename; check the `model.name` field for the actual base model. |
| `model/Modelfile` | Ollama model definition. | Used by `ollama create finedgar -f Modelfile`. |

## Scripts

| File | Owns | Notes |
|---|---|---|
| `scripts/bootstrap_data.py` | End-to-end corpus bootstrap. | Downloads XBRL facts and filings, parses documents, and writes chunks. |
| `scripts/build_vector_index.py` | FAISS index build. | Consumes chunk artifacts and writes vector indexes. |
| `scripts/run_financebench_eval.py` | FinanceBench evaluation runner. | Produces detailed JSON results with route, prediction, scoring, latency, and recall. |
| `scripts/summarize_evals.py` | Evaluation summary. | Turns eval JSON outputs into Markdown and CSV summaries. |
| `scripts/build_financebench_manifest.py` | Benchmark manifest build. | Converts source benchmark rows into normalized local metadata. |
| `scripts/check_benchmark_leakage.py` | Leakage guard. | Fails when training records overlap eval-only benchmark tuples. |
| `scripts/audit_coverage.py` | Data coverage audit. | Reports whether expected ticker/year artifacts exist. |
| `scripts/sync_benchmark_companies.py` | Company catalog sync. | Aligns benchmark companies with local SEC lookup data. |
| `scripts/orchestrate.sh` | Older end-to-end training/eval runner. | Useful as a reference, but README notes it should be parameterized before broad reuse. |
| `scripts/docker/compose.sh` | Compose workflow wrapper. | Selects overlays, detects CPU/GPU target, and exposes common app/data/eval/train/admin commands. |
| `scripts/k8s/*.sh` | Kubernetes lab commands. | Cluster lifecycle, platform install, image build, Helm deploy, jobs, load test, GPU smoke test, and inspection. |

## Docker And Compose

| File | Owns | Notes |
|---|---|---|
| `docker/Dockerfile.runtime` | Runtime and web images. | `runtime` target installs Python dependencies; `web` target adds the built React bundle. |
| `docker/Dockerfile.train` | CUDA training image. | Used only for NVIDIA training workflows. |
| `docker/compose/base.yml` | Shared Compose foundation. | Ollama, network, and cache volumes. |
| `docker/compose/db.yml` | Postgres and migration runner. | Included automatically by `dev` and `inference`. |
| `docker/compose/dev.yml` | Development stack. | Reloadable API and Vite dev server. |
| `docker/compose/inference.yml` | Production-style local stack. | Single FastAPI service serving the built frontend. |
| `docker/compose/data.yml` | Bootstrap/index jobs. | One-shot data artifact workflows. |
| `docker/compose/eval.yml` | Evaluation job. | Runs FinanceBench eval in the runtime container. |
| `docker/compose/train.nvidia.yml` | GPU training jobs. | Requires Linux NVIDIA/CUDA. |
| `docker/compose/admin.yml` | Dozzle admin console. | Local container log viewer. |
| `docker/compose/admin.auth.yml` | Dozzle auth overlay. | Use before exposing Dozzle beyond loopback. |

## Helm Chart

| Path | Owns | Notes |
|---|---|---|
| `charts/finedgar/Chart.yaml` | Chart metadata. | Chart identity and version. |
| `charts/finedgar/values.yaml` | Default values. | Image repositories/tags, config, secrets, resources, PVCs, Postgres, gateway, jobs, observability, and GPU options. |
| `charts/finedgar/values.local.yaml` | Local lab overrides. | k3d-oriented defaults. |
| `charts/finedgar/values.autoscaling.yaml` | HPA profile. | Enables API scaling demo. |
| `charts/finedgar/values.observability.yaml` | Metrics/tracing profile. | Enables ServiceMonitor and OTLP endpoint wiring. |
| `charts/finedgar/values.gpu.yaml` | GPU profile. | Enables NVIDIA scheduling settings. |
| `charts/finedgar/values.finedgar-model.yaml` | Real-model profile. | Uses the local FinEdgar model rather than the tiny demo model. |
| `charts/finedgar/templates/` | Kubernetes manifests. | Deployment, Services, Gateway, PVCs, Secret, ConfigMap, Jobs, CronJob, HPA, ServiceMonitor, Ollama, and CloudNativePG resources. |

## CI

| File | Owns | Notes |
|---|---|---|
| `.github/workflows/main-verify.yml` | Main branch verification. | Runs backend tests, frontend build, Helm lint/template, and Docker builds with `push: false`. |

## Tests

| File | Coverage |
|---|---|
| `backend/tests/test_data_pipeline.py` | Ticker resolution, XBRL lookup, metric aliases, section parsing, and chunking. |
| `backend/tests/test_benchmark_safety.py` | Benchmark tuple governance, metric extraction, reasoning functions, retrieval behavior, route planning, and leakage checks. |
| `backend/tests/test_webapp_auth_history.py` | Registration, verification, login, reset, token reuse rejection, and conversation ownership. |

Run the current suite with:

```bash
python -m pytest backend/tests/ -v
```

## Where To Make Common Changes

| Change | Start here | Also check |
|---|---|---|
| Add a financial metric alias | `backend/data/xbrl_fetcher.py` | `backend/data/benchmarking.py`, `backend/tests/test_benchmark_safety.py` |
| Add a derived XBRL formula | `backend/data/xbrl_reasoning.py` | `backend/data/answer_pipeline.py`, evaluator tests |
| Improve retrieval quality | `backend/data/retrieval.py` | `backend/data/embeddings.py`, `backend/data/reranker.py`, eval output |
| Change chat API shape | `webapp/backend/schemas.py` | `webapp/frontend/src/api.ts`, `services/pipeline.py`, frontend components |
| Change auth behavior | `webapp/backend/security.py` and `services/auth.py` | `docs/auth.md`, auth/history tests |
| Change database schema | `webapp/backend/db_models.py` | Alembic migration, `docs/database.md`, tests |
| Add admin dashboard data | `webapp/backend/routes/admin.py` | `AdminDashboard.tsx`, `docs/admin.md` |
| Change local Docker flow | `scripts/docker/compose.sh` | `docs/docker.md`, `docker/compose/README.md` |
| Change Kubernetes deployment | `charts/finedgar/` | `docs/kubernetes*.md`, `scripts/k8s/*.sh` |
| Change CI verification | `.github/workflows/main-verify.yml` | `docs/architecture.md` CI diagram |
