#!/usr/bin/env bash
set -euo pipefail

kubectl get gateway,httproute,svc,pods,pvc,hpa,jobs -n finedgar
kubectl get cluster -n finedgar
