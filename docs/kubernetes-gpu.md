# Kubernetes GPU Profile

GPU support is optional and not required for the local CPU lab.

The GPU profile exists to run Ollama or training workloads on NVIDIA hardware
when Docker and k3d can expose the GPU into Kubernetes.

First verify Docker can see the GPU:

```bash
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

Run a disposable k3d Kubernetes GPU smoke test:

```bash
scripts/k8s/toolbox.sh scripts/k8s/gpu-smoke-test.sh
```

This creates a separate `finedgar-gpu-test` cluster with `--gpus all`, installs
the NVIDIA Kubernetes device plugin, runs a pod that requests
`nvidia.com/gpu: 1`, and prints `nvidia-smi` from inside Kubernetes.

Delete the disposable test cluster afterward:

```bash
CLUSTER_NAME=finedgar-gpu-test scripts/k8s/toolbox.sh scripts/k8s/delete-cluster.sh
```

If the smoke test reports low inotify limits, raise them on the WSL/Linux host:

```bash
sudo sysctl -w fs.inotify.max_user_instances=1024
sudo sysctl -w fs.inotify.max_user_watches=1048576
sudo sysctl -w fs.inotify.max_queued_events=32768
```

The failure mode looks like this in k3s/containerd logs:

```text
failed to create fsnotify watcher: too many open files
```

On WSL, Docker GPU access can pass while Kubernetes GPU scheduling still fails.
The usual symptom is:

```text
Incompatible strategy detected auto
failed to construct resource managers: invalid device discovery strategy
```

That means the k3d node can see WSL GPU plumbing such as `/dev/dxg`, but the
official NVIDIA Kubernetes device plugin did not discover normal
`nvidia.com/gpu` capacity.

Create the main FinEdgar cluster with GPU passthrough:

```bash
GPU_ENABLED=1 AGENTS=0 scripts/k8s/toolbox.sh scripts/k8s/create-cluster.sh
scripts/k8s/toolbox.sh scripts/k8s/install-gpu-support.sh
```

Deploy the profile:

```bash
scripts/k8s/toolbox.sh scripts/k8s/deploy.sh gpu
```

## Requirements

Before this can run on real GPU hardware, the cluster needs:

- NVIDIA GPU
- NVIDIA drivers on the host
- NVIDIA Container Toolkit
- NVIDIA Kubernetes device plugin
- nodes labeled for GPU scheduling

The chart uses:

```yaml
resources:
  limits:
    nvidia.com/gpu: 1
```

## What The Profile Changes

- `FINEDGAR_FORCE_CPU=0`
- Ollama requests one GPU
- optional training Job requests one GPU
- GPU node selector is added

## Local Non-GPU Machines

Do not use this profile on ordinary local machines. Use:

```bash
scripts/k8s/deploy.sh local
```

The GPU profile is included for learning, chart completeness, and future
hardware expansion.
