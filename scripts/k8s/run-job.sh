#!/usr/bin/env bash
set -euo pipefail

JOB="${1:-}"
PROFILE="${PROFILE:-local}"
BASE_VALUES=(-f charts/finedgar/values.local.yaml)

if [[ "${PROFILE}" == "observability" ]]; then
  BASE_VALUES=(-f charts/finedgar/values.local.yaml -f charts/finedgar/values.observability.yaml)
elif [[ "${PROFILE}" == "autoscaling" ]]; then
  BASE_VALUES=(-f charts/finedgar/values.local.yaml -f charts/finedgar/values.autoscaling.yaml)
fi

case "${JOB}" in
  data-bootstrap)
    SET_VALUES=(--set jobs.dataBootstrap.enabled=true --set jobs.indexBuilder.enabled=false --set jobs.eval.enabled=false)
    ;;
  index)
    SET_VALUES=(--set jobs.dataBootstrap.enabled=false --set jobs.indexBuilder.enabled=true --set jobs.eval.enabled=false)
    ;;
  eval)
    SET_VALUES=(--set jobs.dataBootstrap.enabled=false --set jobs.indexBuilder.enabled=false --set jobs.eval.enabled=true)
    ;;
  all)
    SET_VALUES=(--set jobs.dataBootstrap.enabled=true --set jobs.indexBuilder.enabled=true --set jobs.eval.enabled=true)
    ;;
  *)
    echo "Usage: scripts/k8s/run-job.sh data-bootstrap|index|eval|all" >&2
    exit 1
    ;;
esac

helm upgrade --install finedgar charts/finedgar \
  --namespace finedgar \
  "${BASE_VALUES[@]}" \
  "${SET_VALUES[@]}"

echo "Submitted ${JOB}. Watch jobs with:"
echo "kubectl get jobs,pods -n finedgar"
