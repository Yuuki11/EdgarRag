# FinEdgar RAG

FinEdgar is a local question-answering system for SEC filings. It uses two answer paths:

- XBRL lookups for structured financial facts and ratios.
- Retrieval over filing text for narrative questions.

The model is served locally through Ollama. SEC filings and XBRL facts are downloaded from EDGAR, cached under `data/`, indexed locally, and used by the answer pipeline.

## Documentation

Start with [docs/README.md](docs/README.md) for the organized documentation
map. The main architecture diagrams and request/data flow notes live in
[docs/architecture.md](docs/architecture.md). For file-level ownership and
change guidance, use [docs/codebase-map.md](docs/codebase-map.md).

## Current Result

The latest tracked FinanceBench run is:

| Run | Overall | XBRL | RAG | Recall@5 | Avg latency |
|---|---:|---:|---:|---:|---:|
| [eval_latest_model_20260414.json](outputs/eval_runs/eval_latest_model_20260414.json) | 40.7% | 40.0% | 41.1% | 30.0% | 2,144 ms |

Earlier runs are stored in [outputs/eval_runs/](outputs/eval_runs/). Refresh the summary table with:

```bash
python scripts/summarize_evals.py
```

## How It Works

For the full system diagrams, see [docs/architecture.md](docs/architecture.md).

```
question
  |
  +-- parse ticker, fiscal year, metric, and operation
  |
  +-- XBRL route
  |     +-- read SEC companyfacts cache
  |     +-- select annual facts
  |     +-- compute lookup or ratio
  |
  +-- RAG route
        +-- retrieve filing chunks
        +-- rerank evidence
        +-- call local Ollama model
```

Important modules:

- [backend/data/answer_pipeline.py](backend/data/answer_pipeline.py): routing, fallback, citations, and final answer formatting.
- [backend/data/xbrl_fetcher.py](backend/data/xbrl_fetcher.py): SEC companyfacts fetch and metric lookup.
- [backend/data/xbrl_reasoning.py](backend/data/xbrl_reasoning.py): deterministic financial calculations.
- [backend/data/retrieval.py](backend/data/retrieval.py): filing retrieval and context selection.
- [backend/data/section_parser.py](backend/data/section_parser.py): 10-K section parsing.
- [model/training/](model/training/): dataset preparation, QLoRA training, export, and verification.
- [webapp/](webapp/): FastAPI and React interface.

## Data Pipeline

The ingestion flow is:

1. Resolve ticker to SEC CIK.
2. Fetch XBRL company facts.
3. Download supported filings.
4. Parse filing text.
5. Split text into chunks with provenance.
6. Build FAISS indexes.

Run the default corpus build:

```bash
python scripts/bootstrap_data.py
python scripts/build_vector_index.py
```

Useful data paths:

| Path | Contents |
|---|---|
| `data/company_tickers.json` | Cached SEC ticker table |
| `data/xbrl_cache/` | SEC companyfacts JSON |
| `data/filings/` | Raw filing documents |
| `data/parsed/` | Parsed section or document text |
| `data/chunks/` | Retrieval chunks |
| `data/vector_index/` | FAISS indexes |

## Setup

Create an environment and install the runtime dependencies:

```bash
conda create -n finedgar python=3.11 -y
conda activate finedgar
pip install -r requirements.txt
```

Create `.env` at the repo root:

```bash
SEC_USER_AGENT="<project-or-contact> <email>"
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=finedgar
CHROMADB_PATH=./data/vector_index
```

The SEC requires a descriptive `User-Agent` for API requests. Use a contact string appropriate for the environment where this runs.

## Model Weights

The LoRA adapter is available on Hugging Face:

- [Rakshi1511/finedgar-gemma-4-e2b-lora](https://huggingface.co/Rakshi1511/finedgar-gemma-4-e2b-lora)

This repo contains the adapter weights and tokenizer files. Users still need access to the base model, `google/gemma-4-e2b-it`, and must follow the base model license and terms.

## Ollama Model

Register the local model after a GGUF file exists under `model/gguf/`:

```bash
cd model
ollama create finedgar -f Modelfile
cd ..
```

Verify the model:

```bash
python model/training/verify_model.py --model finedgar
```

## Training

Training is optional if a compatible exported model is already available.

```bash
python model/training/prepare_data.py --sources convfinqa,phrasebank,xbrl_qa,diff_summaries
python model/training/prepare_data.py --combine
python model/training/prepare_data.py --validate data/training/finedgar_train.jsonl
python model/training/train.py --config model/configs/qlora_e4b.yaml
python model/training/export.py
```

The active config file is [model/configs/qlora_e4b.yaml](model/configs/qlora_e4b.yaml). The filename is historical; check the `model.name` field for the active base model.

## Evaluation

Run the FinanceBench evaluation:

```bash
python scripts/run_financebench_eval.py \
  --output outputs/eval_runs/eval_$(date +%Y%m%d_%H%M%S).json
```

Each output JSON contains the question, gold answer, prediction, route, latency, scores, and retrieval recall.

## Web App

The web app wraps the same answer pipeline and now requires Postgres-backed
email/password authentication. Chat conversations and messages are persisted per
user.

```bash
cp .env.example .env
# Fill SEC_USER_AGENT, POSTGRES_PASSWORD, and FINEDGAR_AUTH_SECRET.
scripts/docker/compose.sh dev up
```

Open `http://localhost:5173`. The authenticated operator dashboard is available
at `http://localhost:5173/admin`.

Local auth email defaults to console mode. Registration, verification, and
password reset links are printed in the backend container logs:

```bash
scripts/docker/compose.sh dev logs web-api-dev
```

For single-port production-style testing:

```bash
scripts/docker/compose.sh inference up -d
scripts/docker/compose.sh db migrate
```

Open `http://localhost:8000`. More details are in
[webapp/README.md](webapp/README.md), [docs/auth.md](docs/auth.md), and
[docs/database.md](docs/database.md).

## Docker

Docker workflows are split by use case and are wrapped by an auto-detecting helper:

```bash
scripts/docker/compose.sh inference up -d
scripts/docker/compose.sh dev up
scripts/docker/compose.sh admin up -d
scripts/docker/compose.sh db migrate
scripts/docker/compose.sh db shell
scripts/docker/compose.sh data bootstrap -- --limit 3
scripts/docker/compose.sh data index
scripts/docker/compose.sh eval run -- --limit 5
```

The wrapper selects `linux-nvidia` when Linux + NVIDIA/CUDA is available, otherwise `mac-cpu`. QLoRA training is available only on Linux NVIDIA hosts:

```bash
scripts/docker/compose.sh train check
scripts/docker/compose.sh train prepare
scripts/docker/compose.sh train run
scripts/docker/compose.sh train export
scripts/docker/compose.sh train verify
```

Ollama and Postgres run as separate Compose services. Application containers use
`OLLAMA_HOST=http://ollama:11434` and
`DATABASE_URL=postgresql+asyncpg://...@postgres:5432/...`. See
[docs/docker.md](docs/docker.md) for the full workflow reference.

## Admin Console

The web app includes an authenticated operator dashboard at `/admin`. It shows
Ollama health, compute mode, indexed data status, database activity, recent auth
events, and Kubernetes pod metadata when deployed with Helm.

For live container logs, start the standalone admin console:

```bash
scripts/docker/compose.sh admin up -d
```

Open the in-app dashboard at `http://localhost:8000/admin` for production-style
local runs or `http://finedgar.localhost/admin` in the k3d lab. Open Dozzle at
`http://localhost:8081`. Dozzle runs as its own Compose project and is filtered
to FinEdgar containers by default. Keep it loopback-only for local work, or use
the authenticated overlay before exposing it beyond your machine:

```bash
scripts/docker/compose.sh admin generate-user admin -- \
  --password '<strong-password>' \
  --user-roles none \
  > docker/admin/users.yml
scripts/docker/compose.sh admin up-auth -d
```

See [docs/admin.md](docs/admin.md) for security notes and operational details.

## Kubernetes Local Lab

FinEdgar also includes a zero-cloud-cost Kubernetes track for portfolio demos
and platform learning. It uses k3d, Helm, Gateway API, CloudNativePG, HPA, k6,
Prometheus, Grafana, Loki, Tempo, and OpenTelemetry.

```bash
scripts/k8s/create-cluster.sh
scripts/k8s/install-platform.sh
scripts/k8s/build-images.sh
scripts/k8s/deploy.sh local
```

Open `http://finedgar.localhost`. Autoscaling and observability profiles are
available with:

```bash
scripts/k8s/deploy.sh autoscaling
scripts/k8s/load-test.sh
scripts/k8s/deploy.sh observability
scripts/k8s/deploy.sh full
scripts/k8s/run-job.sh eval
```

This deployment path is local-only: no VPS, cloud account, paid domain, or
public TLS is required. Start with [docs/kubernetes.md](docs/kubernetes.md), then
read [docs/kubernetes-architecture.md](docs/kubernetes-architecture.md),
[docs/kubernetes-autoscaling.md](docs/kubernetes-autoscaling.md), and
[docs/kubernetes-observability.md](docs/kubernetes-observability.md).

## Tests

```bash
pytest backend/tests/ -v
```

Current tests cover ticker resolution, XBRL fetching, section parsing, chunking,
benchmark leakage checks, auth token behavior, and chat history ownership.

## Known Gaps

- Retrieval recall is still the main limiter for RAG answers.
- Some narrative questions retrieve useful evidence but produce incomplete answers.
- XBRL handling still needs more special cases for less common formulas and concept families.
- The orchestrator script should be parameterized before relying on it in another environment.
- CI is verification-only: pushes to `main` run tests, frontend build, Helm
  rendering, and Docker image builds without pushing or deploying.
- Public deployments must configure HTTPS, SMTP, strong auth secrets, and
  durable Postgres backups before opening registration.
