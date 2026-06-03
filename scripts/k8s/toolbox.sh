#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="${FINEDGAR_K8S_TOOLBOX_IMAGE:-alpine:3.20}"
CLUSTER_NAME="${CLUSTER_NAME:-finedgar}"

if [[ $# -eq 0 ]]; then
  set -- sh
fi

docker run --rm --network host \
  -e CLUSTER_NAME="$CLUSTER_NAME" \
  -e REGISTRY_NAME="${REGISTRY_NAME:-}" \
  -e REGISTRY_PORT="${REGISTRY_PORT:-}" \
  -e API_PORT="${API_PORT:-}" \
  -e HTTP_PORT="${HTTP_PORT:-}" \
  -e AGENTS="${AGENTS:-}" \
  -e GPU_ENABLED="${GPU_ENABLED:-}" \
  -e DEVICE_PLUGIN_VERSION="${DEVICE_PLUGIN_VERSION:-}" \
  -e DEVICE_PLUGIN_URL="${DEVICE_PLUGIN_URL:-}" \
  -e TEST_POD="${TEST_POD:-}" \
  -e CUDA_IMAGE="${CUDA_IMAGE:-}" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$ROOT:/work" \
  -w /work \
  "$IMAGE" sh -lc '
    set -euo pipefail
    apk add --no-cache bash curl ca-certificates docker-cli git openssl tar gzip >/dev/null
    if ! command -v k3d >/dev/null 2>&1; then
      curl -fsSL -o /tmp/install-k3d.sh https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh
      bash /tmp/install-k3d.sh >/dev/null
    fi
    if ! command -v kubectl >/dev/null 2>&1; then
      KUBECTL_VERSION="$(curl -fsSL https://dl.k8s.io/release/stable.txt)"
      curl -fsSL -o /usr/local/bin/kubectl "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl"
      chmod +x /usr/local/bin/kubectl
    fi
    if ! command -v helm >/dev/null 2>&1; then
      curl -fsSL -o /tmp/get_helm.sh https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3
      chmod 700 /tmp/get_helm.sh
      /tmp/get_helm.sh >/dev/null
    fi
    if k3d cluster list | grep -q "^${CLUSTER_NAME}"; then
      k3d kubeconfig get "$CLUSTER_NAME" > /tmp/finedgar-kubeconfig
      export KUBECONFIG=/tmp/finedgar-kubeconfig
    fi
    exec "$@"
  ' sh "$@"
