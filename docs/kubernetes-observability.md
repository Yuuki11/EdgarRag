# Kubernetes Observability

The local platform installs:

- Prometheus through kube-prometheus-stack
- Grafana
- Loki
- Promtail
- Tempo
- OpenTelemetry Collector

Install platform dependencies:

```bash
scripts/k8s/install-platform.sh
```

Deploy FinEdgar with tracing and ServiceMonitor enabled:

```bash
scripts/k8s/deploy.sh observability
```

## Application Metrics

FinEdgar exposes Prometheus metrics at:

```text
/metrics
```

Important metrics:

- `finedgar_http_requests_total`
- `finedgar_http_request_duration_seconds`
- `finedgar_chat_requests_total`
- `finedgar_chat_duration_seconds`
- `finedgar_ollama_requests_total`
- `finedgar_ollama_request_duration_seconds`
- `finedgar_pipeline_errors_total`

## Tracing

Tracing is enabled by:

```text
FINEDGAR_OTEL_ENABLED=1
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector.observability:4317
```

The app traces:

- FastAPI request lifecycle
- HTTPX calls
- chat pipeline execution
- chat persistence block
- Ollama generate calls

## Grafana

Port-forward Grafana:

```bash
kubectl port-forward -n observability svc/kube-prometheus-stack-grafana 3000:80
```

Open:

```text
http://localhost:3000
```

Default credentials:

```text
admin / admin
```

The repo includes a starter FinEdgar dashboard ConfigMap under
`deploy/k8s/grafana/dashboards/`.

## Logs

Promtail ships pod logs to Loki. In Grafana Explore, query:

```text
{namespace="finedgar"}
```

## Traces

Tempo receives traces from the OpenTelemetry Collector. In Grafana Explore,
choose the Tempo data source and search recent traces for the FinEdgar service.

## Practical Limits

The observability stack is intentionally complete, but it consumes local memory.
If Docker Desktop or the host is memory constrained, deploy `local` first and add
the observability profile after the base app works.
