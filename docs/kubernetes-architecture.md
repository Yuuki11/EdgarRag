# Kubernetes Architecture

The Kubernetes deployment mirrors the existing Compose design while using native
Kubernetes workload types.

```text
Browser
  |
Gateway API
  |
web-api Service
  |
web-api Pods
  |      \
  |       -> CloudNativePG Postgres
  |
  -> Ollama Service -> Ollama StatefulSet

PVCs:
  data, outputs, ollama model cache, Hugging Face cache, Torch cache
```

## Workload Mapping

| FinEdgar component | Kubernetes resource |
|---|---|
| FastAPI + built React app | Deployment |
| Public local HTTP route | Gateway + HTTPRoute |
| Internal load balancing | Service |
| Ollama model server | StatefulSet |
| Auth/chat database | CloudNativePG Cluster |
| Alembic migration | Job |
| EDGAR bootstrap | Job |
| FAISS index build | Job |
| FinanceBench eval | Job |
| Scheduled smoke eval | CronJob |
| Non-secret config | ConfigMap |
| Secrets | Secret |
| Model/data/cache storage | PersistentVolumeClaim |

The migration Job is enabled by default. Data bootstrap, index build, and eval
Jobs are explicit on-demand operations through `scripts/k8s/run-job.sh` so the
base local deployment can start quickly.

## Storage Model

FinEdgar currently uses file-based RAG artifacts under `data/`:

- XBRL cache
- downloaded filings
- parsed filing text
- chunks
- FAISS index

The local Kubernetes chart stores these artifacts on PVCs and mounts them into
the API and job pods. This is simple and good for learning.

The main scaling caveat is that file-based local storage is not the same as a
distributed retrieval service. For a future production design, the likely next
step would be object storage plus immutable index artifacts, or a dedicated
retrieval service.

## Database Model

Postgres is managed by CloudNativePG instead of a raw StatefulSet. This teaches
the operator pattern and gives a more realistic lifecycle story for stateful
services.

The migration Job runs:

```bash
alembic upgrade head
```

## Routing Model

The chart uses Gateway API:

- `Gateway` owns the local HTTP listener.
- `HTTPRoute` sends `finedgar.localhost` traffic to the web service.
- The `Service` load-balances across API pods.
- The default Traefik chart exposes external service port 80 to its internal
  `web` entryPoint on port 8000, so the Gateway listener is configured for
  port 8000 while users still open `http://finedgar.localhost`.

This intentionally avoids cloud load balancers and public TLS.

## Bottlenecks

Autoscaling the API is useful for learning, but it does not remove every
bottleneck:

- one Ollama pod can saturate under chat load
- local storage is not distributed
- model inference is slower than ordinary HTTP handlers
- authenticated chat depends on Postgres and persistent sessions

These constraints are part of the portfolio story: Kubernetes scaling only helps
when the architecture allows the workload to scale.
