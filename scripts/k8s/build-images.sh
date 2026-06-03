#!/usr/bin/env bash
set -euo pipefail

REGISTRY="${REGISTRY:-k3d-finedgar-registry.localhost:5001}"
PUSH_REGISTRY="${PUSH_REGISTRY:-localhost:5001}"
IMAGE_TAG="${IMAGE_TAG:-latest}"

WEB_IMAGE="${REGISTRY}/finedgar-web:${IMAGE_TAG}"
RUNTIME_IMAGE="${REGISTRY}/finedgar-runtime:${IMAGE_TAG}"
TRAIN_IMAGE="${REGISTRY}/finedgar-train:${IMAGE_TAG}"

WEB_PUSH_IMAGE="${PUSH_REGISTRY}/finedgar-web:${IMAGE_TAG}"
RUNTIME_PUSH_IMAGE="${PUSH_REGISTRY}/finedgar-runtime:${IMAGE_TAG}"
TRAIN_PUSH_IMAGE="${PUSH_REGISTRY}/finedgar-train:${IMAGE_TAG}"

docker build -f docker/Dockerfile.runtime --target web -t "${WEB_IMAGE}" -t "${WEB_PUSH_IMAGE}" .
docker build -f docker/Dockerfile.runtime --target runtime -t "${RUNTIME_IMAGE}" -t "${RUNTIME_PUSH_IMAGE}" .

if [[ "${BUILD_TRAIN_IMAGE:-0}" == "1" ]]; then
  docker build -f docker/Dockerfile.train -t "${TRAIN_IMAGE}" -t "${TRAIN_PUSH_IMAGE}" .
fi

docker push "${WEB_PUSH_IMAGE}"
docker push "${RUNTIME_PUSH_IMAGE}"

if [[ "${BUILD_TRAIN_IMAGE:-0}" == "1" ]]; then
  docker push "${TRAIN_PUSH_IMAGE}"
fi
