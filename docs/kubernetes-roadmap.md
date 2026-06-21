# Kubernetes Learning Roadmap

This roadmap is local-only and avoids cloud/VPS cost.

## 1. Cluster Basics

- Create a k3d cluster.
- Learn namespaces, pods, services, deployments, and PVCs.
- Verify traffic with `kubectl`.

## 2. Helm Packaging

- Package FinEdgar as a Helm chart.
- Use values files for local, autoscaling, observability, GPU, and real-model
  profiles.
- Learn how templates, values, and release names interact.

## 3. Stateful Services

- Run Ollama as a StatefulSet.
- Run Postgres through CloudNativePG.
- Understand persistent storage and restart behavior.

## 4. Jobs

- Run Alembic migrations as a Job.
- Run data bootstrap as a Job.
- Run FAISS index building as a Job.
- Run FinanceBench smoke eval as a Job.

## 5. Gateway API And Load Balancing

- Route `finedgar.localhost` through Gateway API.
- Use Services to load-balance API pods.
- Understand the difference between app routing and pod scheduling.

## 6. Autoscaling

- Add metrics-server.
- Enable HPA for `web-api`.
- Use k6 to generate load.
- Observe pod scaling and bottlenecks.

## 7. Observability

- Scrape app metrics with Prometheus.
- Visualize metrics in Grafana.
- Ship logs with Promtail and Loki.
- Send traces through OpenTelemetry Collector to Tempo.

## 8. Optional GPU

- Render GPU-aware manifests.
- Understand `nvidia.com/gpu` scheduling.
- Keep GPU out of the required local workflow.
