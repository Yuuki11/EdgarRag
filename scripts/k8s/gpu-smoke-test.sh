#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-finedgar-gpu-test}"
if [[ "${CLUSTER_NAME}" == "finedgar" && "${FINEDGAR_GPU_SMOKE_ALLOW_MAIN_CLUSTER:-0}" != "1" ]]; then
  CLUSTER_NAME="finedgar-gpu-test"
fi
API_PORT="${API_PORT:-6551}"
HTTP_PORT="${HTTP_PORT:-8081}"
REGISTRY_NAME="${REGISTRY_NAME:-finedgar-gpu-registry.localhost}"
REGISTRY_PORT="${REGISTRY_PORT:-5002}"
TEST_POD="${TEST_POD:-gpu-smoke}"
CUDA_IMAGE="${CUDA_IMAGE:-nvidia/cuda:12.4.1-base-ubuntu22.04}"

INOTIFY_INSTANCES="$(cat /proc/sys/fs/inotify/max_user_instances 2>/dev/null || echo 0)"
if [[ "${INOTIFY_INSTANCES}" -lt 512 ]]; then
  cat >&2 <<EOF
fs.inotify.max_user_instances is ${INOTIFY_INSTANCES}, which is too low for an
additional k3d/k3s cluster in this environment.

Raise it on the host, then rerun this script:

  sudo sysctl -w fs.inotify.max_user_instances=1024
  sudo sysctl -w fs.inotify.max_user_watches=1048576
  sudo sysctl -w fs.inotify.max_queued_events=32768
EOF
  exit 1
fi

export CLUSTER_NAME
export API_PORT
export HTTP_PORT
export REGISTRY_NAME
export REGISTRY_PORT
export AGENTS="${AGENTS:-0}"
export GPU_ENABLED=1

scripts/k8s/create-cluster.sh

if ! scripts/k8s/install-gpu-support.sh; then
  echo
  echo "NVIDIA device plugin did not expose nvidia.com/gpu. Diagnostics:"
  kubectl get nodes -o wide || true
  kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{" allocatable_gpu="}{.status.allocatable.nvidia\.com/gpu}{"\n"}{end}' || true
  kubectl -n kube-system get pods -l app=nvidia-device-plugin-daemonset -o wide || true
  kubectl -n kube-system logs -l app=nvidia-device-plugin-daemonset --tail=120 || true
  cat >&2 <<EOF

Docker can expose GPUs while k3d/Kubernetes still cannot advertise
nvidia.com/gpu. On WSL this commonly means the node container sees /dev/dxg and
WSL driver libraries, but the NVIDIA Kubernetes device plugin cannot initialize
normal Linux NVML discovery.
EOF
  exit 1
fi

kubectl delete pod "${TEST_POD}" --ignore-not-found
kubectl run "${TEST_POD}" \
  --restart=Never \
  --image="${CUDA_IMAGE}" \
  --limits=nvidia.com/gpu=1 \
  --command -- nvidia-smi

kubectl wait --for=condition=Ready "pod/${TEST_POD}" --timeout=180s || true
kubectl wait --for=jsonpath='{.status.phase}'=Succeeded "pod/${TEST_POD}" --timeout=180s
kubectl logs "${TEST_POD}"

echo "GPU smoke test completed on cluster ${CLUSTER_NAME}."
