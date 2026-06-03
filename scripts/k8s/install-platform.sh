#!/usr/bin/env bash
set -euo pipefail

helm repo add traefik https://traefik.github.io/charts >/dev/null
helm repo add cnpg https://cloudnative-pg.github.io/charts >/dev/null
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null
helm repo add grafana https://grafana.github.io/helm-charts >/dev/null
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts >/dev/null
helm repo add metrics-server https://kubernetes-sigs.github.io/metrics-server/ >/dev/null
helm repo update

kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.2.1/standard-install.yaml

helm upgrade --install traefik traefik/traefik \
  --namespace gateway-system \
  --set providers.kubernetesGateway.enabled=true \
  --set service.type=LoadBalancer

helm upgrade --install cloudnative-pg cnpg/cloudnative-pg \
  --namespace cnpg-system

if kubectl get deployment -n kube-system metrics-server >/dev/null 2>&1; then
  echo "Using existing kube-system/metrics-server deployment."
else
  helm upgrade --install metrics-server metrics-server/metrics-server \
    --namespace kube-system \
    --set args="{--kubelet-insecure-tls}"
fi

helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace observability \
  -f deploy/k8s/platform/observability/kube-prometheus-stack-values.yaml

helm upgrade --install loki grafana/loki \
  --namespace observability \
  -f deploy/k8s/platform/observability/loki-values.yaml

helm upgrade --install promtail grafana/promtail \
  --namespace observability \
  -f deploy/k8s/platform/observability/promtail-values.yaml

helm upgrade --install tempo grafana/tempo \
  --namespace observability \
  -f deploy/k8s/platform/observability/tempo-values.yaml

helm upgrade --install otel-collector open-telemetry/opentelemetry-collector \
  --namespace observability \
  -f deploy/k8s/platform/observability/otel-collector-values.yaml

kubectl apply -n observability -f deploy/k8s/grafana/dashboards

echo "Platform installed."
