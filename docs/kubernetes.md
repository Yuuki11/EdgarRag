# Kubernetes Local Lab

FinEdgar has a local Kubernetes deployment path for learning and portfolio demos.
It is intentionally zero-cloud-cost: k3d runs Kubernetes in Docker, the app is
served over local HTTP, and all storage uses local PersistentVolumes.

The Docker Compose workflow remains the simplest development path. Kubernetes is
an additional deployment and platform-engineering track.

## What This Demonstrates

- k3d local Kubernetes cluster
- Helm-packaged FinEdgar application
- Gateway API HTTP routing
- Kubernetes Services for load balancing
- CloudNativePG-managed Postgres
- Stateful Ollama model serving
- Persistent storage for model, RAG data, caches, and outputs
- Jobs for migrations, data bootstrap, indexing, and evaluation
- HPA autoscaling with k6 load tests
- Prometheus, Grafana, Loki, Promtail, Tempo, and OpenTelemetry Collector
- Optional NVIDIA GPU scheduling profile

## Prerequisites

Install these locally:

- Docker
- k3d
- kubectl
- Helm

Optional:

- k6 CLI, if you want to run load tests outside Kubernetes
- NVIDIA device plugin and GPU hardware, only for the optional GPU profile

## Quickstart

Create the cluster:

```bash
scripts/k8s/create-cluster.sh
```

Install platform dependencies:

```bash
scripts/k8s/install-platform.sh
```

Build and push local images into the k3d registry:

```bash
scripts/k8s/build-images.sh
```

Images are tagged as `k3d-finedgar-registry.localhost:5001/finedgar-*`, which
matches the local k3d registry created by `scripts/k8s/create-cluster.sh`.
Docker pushes through `localhost:5001` by default because that is the host
port exposed by the registry container.

For a cache-proof rebuild, use a unique tag:

```bash
IMAGE_TAG=admin-ui-20260425 scripts/k8s/build-images.sh
IMAGE_TAG=admin-ui-20260425 IMAGE_PULL_POLICY=Always scripts/k8s/deploy.sh local
```

Deploy FinEdgar:

```bash
scripts/k8s/deploy.sh local
```

The deployment starts the app and also creates a non-blocking Ollama model-pull
Job. The first model download can take several minutes.

Watch the deployment:

```bash
scripts/k8s/status.sh
kubectl get pods -n finedgar -w
```

Open:

```text
http://finedgar.localhost
```

The in-app admin dashboard is available after sign-in:

```text
http://finedgar.localhost/admin
```

Use it to confirm pod metadata, runtime release, data artifact status, indexed
company count, Ollama reachability, auth activity, and links to `/healthz` and
`/metrics`.

Run optional pipeline jobs when needed:

```bash
scripts/k8s/run-job.sh data-bootstrap
scripts/k8s/run-job.sh index
scripts/k8s/run-job.sh eval
```

If your OS does not resolve `*.localhost`, add this host entry:

```text
127.0.0.1 finedgar.localhost
```

## Deployment Profiles

Local CPU profile:

```bash
scripts/k8s/deploy.sh local
```

Autoscaling profile:

```bash
scripts/k8s/deploy.sh autoscaling
```

Observability profile:

```bash
scripts/k8s/deploy.sh observability
```

Autoscaling plus observability:

```bash
scripts/k8s/deploy.sh full
```

Use the real FinEdgar Ollama model when the GGUF exists locally and the Ollama
model has been created:

```bash
scripts/k8s/deploy.sh finedgar-model
```

Optional GPU profile:

```bash
GPU_ENABLED=1 AGENTS=0 scripts/k8s/toolbox.sh scripts/k8s/create-cluster.sh
scripts/k8s/toolbox.sh scripts/k8s/install-gpu-support.sh
scripts/k8s/toolbox.sh scripts/k8s/deploy.sh gpu
```

Disposable Kubernetes GPU smoke test:

```bash
scripts/k8s/toolbox.sh scripts/k8s/gpu-smoke-test.sh
```

## Model Choice

The default Kubernetes lab uses `qwen2.5:0.5b` because it is small enough for
infrastructure demos. This keeps memory use practical while learning Kubernetes.

For answer quality, use the real FinEdgar model:

```bash
scripts/k8s/deploy.sh finedgar-model
```

That profile assumes the model is already available to Ollama. The repo does not
commit GGUF weights.

## Common Commands

Port-forward Grafana:

```bash
kubectl port-forward -n observability svc/kube-prometheus-stack-grafana 3000:80
```

Default local Grafana credentials:

```text
admin / admin
```

Run the k6 load test inside Kubernetes:

```bash
scripts/k8s/load-test.sh
```

Run all data/eval jobs:

```bash
scripts/k8s/run-job.sh all
```

Check HPA:

```bash
kubectl get hpa -n finedgar -w
```

Show app logs:

```bash
kubectl logs -n finedgar deploy/finedgar-finedgar-web -f
```

Tear down the local cluster:

```bash
scripts/k8s/delete-cluster.sh
```

## Notes

- This path is local-only and does not require a VPS, cloud account, paid domain,
  or public TLS.
- The app uses HTTP locally, so `FINEDGAR_AUTH_COOKIE_SECURE=0`.
- The Kubernetes chart is designed for learning and portfolio use, not as a
  hardened internet-facing deployment.
- File-based RAG artifacts are stored on PVCs. Horizontal API scaling works for
  Kubernetes learning, but Ollama and shared local storage remain bottlenecks.
