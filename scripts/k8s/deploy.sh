#!/usr/bin/env bash
set -euo pipefail

PROFILE="${1:-local}"
EXTRA_VALUES=()
EXTRA_SET_ARGS=()

case "${PROFILE}" in
  local)
    EXTRA_VALUES=(-f charts/finedgar/values.local.yaml)
    ;;
  autoscaling)
    EXTRA_VALUES=(-f charts/finedgar/values.local.yaml -f charts/finedgar/values.autoscaling.yaml)
    ;;
  observability)
    EXTRA_VALUES=(-f charts/finedgar/values.local.yaml -f charts/finedgar/values.observability.yaml)
    ;;
  full)
    EXTRA_VALUES=(-f charts/finedgar/values.local.yaml -f charts/finedgar/values.autoscaling.yaml -f charts/finedgar/values.observability.yaml)
    ;;
  gpu)
    EXTRA_VALUES=(-f charts/finedgar/values.local.yaml -f charts/finedgar/values.gpu.yaml)
    ;;
  finedgar-model)
    EXTRA_VALUES=(-f charts/finedgar/values.local.yaml -f charts/finedgar/values.finedgar-model.yaml)
    ;;
  *)
    echo "Unknown profile: ${PROFILE}" >&2
    echo "Use one of: local, autoscaling, observability, full, gpu, finedgar-model." >&2
    exit 1
    ;;
esac

if [[ -n "${IMAGE_TAG:-}" ]]; then
  EXTRA_SET_ARGS+=(--set "image.tag=${IMAGE_TAG}" --set "runtimeImage.tag=${IMAGE_TAG}")
fi

if [[ -n "${IMAGE_PULL_POLICY:-}" ]]; then
  EXTRA_SET_ARGS+=(--set "image.pullPolicy=${IMAGE_PULL_POLICY}" --set "runtimeImage.pullPolicy=${IMAGE_PULL_POLICY}")
fi

helm upgrade --install finedgar charts/finedgar \
  --namespace finedgar \
  "${EXTRA_VALUES[@]}" \
  "${EXTRA_SET_ARGS[@]}"

echo "Deployment submitted. Watch with:"
echo "kubectl get pods -n finedgar -w"
