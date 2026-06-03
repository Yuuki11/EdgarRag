#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-finedgar}"
k3d cluster delete "${CLUSTER_NAME}"
