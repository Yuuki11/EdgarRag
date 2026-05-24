# Compose Files

Use `scripts/docker/compose.sh` from the repo root for normal workflows. It loads these files with `--project-directory` set to the repo root so build contexts and bind mounts resolve consistently.

- `base.yml`: shared Ollama service, network, and named volumes.
- `db.yml`: Postgres 18 service, healthcheck, persistent database volume, and Alembic migration runner.
- `admin.yml`: standalone Dozzle admin console for live Docker logs.
- `admin.auth.yml`: optional auth overlay for the admin console.
- `inference.yml`: production FastAPI plus built React bundle.
- `dev.yml`: reloadable FastAPI and Vite dev server.
- `data.yml`: one-shot data bootstrap and index builder.
- `eval.yml`: one-shot FinanceBench evaluation.
- `train.nvidia.yml`: CUDA/Unsloth QLoRA training jobs.

Direct Compose example:

```bash
docker compose --project-directory . \
  -f docker/compose/base.yml \
  -f docker/compose/db.yml \
  -f docker/compose/inference.yml \
  up -d
```

Standalone admin console example:

```bash
docker compose --project-directory . \
  -f docker/compose/admin.yml \
  up -d
```
