#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-finedgar}"
REGISTRY_NAME="${REGISTRY_NAME:-finedgar-registry.localhost}"
REGISTRY_PORT="${REGISTRY_PORT:-5001}"
API_PORT="${API_PORT:-6550}"
HTTP_PORT="${HTTP_PORT:-80}"
AGENTS="${AGENTS:-2}"
GPU_ENABLED="${GPU_ENABLED:-0}"
NOFILE_LIMIT="${NOFILE_LIMIT:-1048576}"

if ! command -v k3d >/dev/null 2>&1; then
  echo "k3d is required. Install it from https://k3d.io/." >&2
  exit 1
fi

if ! command -v kubectl >/dev/null 2>&1; then
  echo "kubectl is required." >&2
  exit 1
fi

if ! k3d registry list | grep -Eq "^(k3d-)?${REGISTRY_NAME}[[:space:]]"; then
  k3d registry create "${REGISTRY_NAME}" --port "${REGISTRY_PORT}"
fi

if k3d cluster list | grep -q "^${CLUSTER_NAME}"; then
  echo "k3d cluster ${CLUSTER_NAME} already exists."
else
  CREATE_ARGS=(
    "${CLUSTER_NAME}"
    --registry-use "k3d-${REGISTRY_NAME}:${REGISTRY_PORT}" \
    --api-port "${API_PORT}" \
    --agents "${AGENTS}" \
    --runtime-ulimit "nofile=${NOFILE_LIMIT}:${NOFILE_LIMIT}" \
    --k3s-arg "--disable=traefik@server:0" \
    -p "${HTTP_PORT}:80@loadbalancer"
  )

  if [[ "${GPU_ENABLED}" == "1" ]]; then
    CREATE_ARGS+=(--gpus all)
  fi

  k3d cluster create "${CREATE_ARGS[@]}"
fi

kubectl create namespace finedgar --dry-run=client -o yaml | kubectl apply -f -
kubectl create namespace observability --dry-run=client -o yaml | kubectl apply -f -
kubectl create namespace cnpg-system --dry-run=client -o yaml | kubectl apply -f -
kubectl create namespace gateway-system --dry-run=client -o yaml | kubectl apply -f -

echo "Cluster ready. Add this host entry if your OS does not resolve *.localhost:"
echo "127.0.0.1 finedgar.localhost"
if [[ "${GPU_ENABLED}" == "1" ]]; then
  echo "GPU passthrough enabled for k3d node containers. Run scripts/k8s/install-gpu-support.sh next."
fi
