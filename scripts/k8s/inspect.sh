#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

"$ROOT/scripts/k8s/toolbox.sh" sh -lc '
  set -euo pipefail

  echo "== Nodes =="
  kubectl get nodes -o wide

  echo
  echo "== FinEdgar =="
  kubectl get pods,svc,pvc,jobs,hpa,gateway,httproute -n finedgar
  kubectl get cluster -n finedgar || true

  echo
  echo "== Observability =="
  kubectl get pods -n observability

  echo
  echo "== Gateway Health =="
  curl -fsS -H "Host: finedgar.localhost" http://127.0.0.1/healthz

  echo
  echo
  echo "== Metrics Sample =="
  curl -fsS -H "Host: finedgar.localhost" http://127.0.0.1/metrics \
    | grep -E "finedgar_http_requests_total|finedgar_http_request_duration_seconds_count|finedgar_chat_requests_total|finedgar_ollama_requests_total" \
    | head -30 || true

  echo
  echo "== Recent FinEdgar Events =="
  kubectl get events -n finedgar --sort-by=.lastTimestamp | tail -40
'
