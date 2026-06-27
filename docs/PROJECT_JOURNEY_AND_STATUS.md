# Project Journey And Status

FinEdgar started as a local SEC filing QA system and now has three working
tracks: a data/retrieval pipeline, an authenticated web app, and a local
Kubernetes platform lab.

## Current Capability

- Structured financial facts can be answered through SEC XBRL companyfacts.
- Narrative questions can be answered through retrieval over parsed filing
  chunks and local Ollama generation.
- The web app supports email/password accounts, verification, reset-password,
  session cookies, chat history, and conversation ownership.
- Docker Compose covers development, inference-style local serving, Postgres,
  data jobs, evaluation, training, and admin logs.
- The Kubernetes lab covers Helm, Gateway API, CloudNativePG, Ollama, jobs, HPA,
  k6, metrics, logs, traces, and optional GPU scheduling.
- GitHub Actions verifies pushes to `main` without pushing images or deploying.

## Current Benchmark Anchor

The latest tracked FinanceBench run in the top-level README is:

| Run | Overall | XBRL | RAG | Recall@5 | Avg latency |
|---|---:|---:|---:|---:|---:|
| `eval_latest_model_20260414.json` | 40.7% | 40.0% | 41.1% | 30.0% | 2,144 ms |

Refresh summaries with:

```bash
python scripts/summarize_evals.py
```

## Main Gaps

- Retrieval recall is still the biggest quality limiter for narrative answers.
- Some narrative answers retrieve useful evidence but produce incomplete final
  wording.
- XBRL coverage needs more special cases for less common formulas and concept
  families.
- The older orchestrator script should be parameterized before it is used as a
  release tool.
- Public deployment still needs HTTPS, SMTP, strong secrets, restricted admin
  access, durable backups, and a clearer role model.

## Near-Term Priorities

1. Improve retrieval quality and evidence selection.
2. Expand deterministic XBRL formula coverage.
3. Add focused tests when changing auth, chat history, metrics, or route
   planning.
4. Keep the verification-only GitHub Actions workflow green on `main`.
5. Treat Kubernetes as a local learning/deployment track until production
   security and backup requirements are finished.
