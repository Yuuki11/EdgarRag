#!/usr/bin/env bash
set -euo pipefail

kubectl apply -n finedgar -f deploy/k8s/k6/k6-configmap.yaml
kubectl delete job -n finedgar finedgar-k6 --ignore-not-found
kubectl apply -n finedgar -f deploy/k8s/k6/k6-job.yaml
kubectl wait -n finedgar --for=condition=complete job/finedgar-k6 --timeout=6m
kubectl logs -n finedgar job/finedgar-k6
