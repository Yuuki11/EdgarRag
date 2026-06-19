#!/usr/bin/env bash
set -euo pipefail

DEVICE_PLUGIN_VERSION="${DEVICE_PLUGIN_VERSION:-v0.19.0}"
DEVICE_PLUGIN_URL="${DEVICE_PLUGIN_URL:-https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/${DEVICE_PLUGIN_VERSION}/deployments/static/nvidia-device-plugin.yml}"

if ! command -v kubectl >/dev/null 2>&1; then
  echo "kubectl is required." >&2
  exit 1
fi

kubectl apply -f "${DEVICE_PLUGIN_URL}"
kubectl -n kube-system rollout status daemonset/nvidia-device-plugin-daemonset --timeout=180s

sleep 5

mapfile -t GPU_NODES < <(
  kubectl get nodes -o jsonpath='{range .items[?(@.status.allocatable.nvidia\.com/gpu)]}{.metadata.name}{"\n"}{end}'
)

if [[ "${#GPU_NODES[@]}" -eq 0 ]]; then
  echo "No Kubernetes nodes currently advertise nvidia.com/gpu." >&2
  echo "Check that the k3d cluster was created with GPU_ENABLED=1 and Docker supports --gpus all." >&2
  exit 1
fi

for node in "${GPU_NODES[@]}"; do
  kubectl label node "${node}" nvidia.com/gpu.present=true --overwrite
done

kubectl get nodes -L nvidia.com/gpu.present \
  -o custom-columns=NAME:.metadata.name,READY:.status.conditions[-1].status,GPU:.status.allocatable.nvidia\\.com/gpu,GPU_PRESENT:.metadata.labels.nvidia\\.com/gpu\\.present

echo "GPU support installed."
