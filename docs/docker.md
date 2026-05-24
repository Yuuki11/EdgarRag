# Docker Workflows

FinEdgar uses split Compose overlays so Ollama, Postgres, the web app, data
jobs, evaluation, and NVIDIA fine-tuning can be managed independently while
sharing the same project network and cache volumes.

## Setup

Create `.env` from `.env.example` and set at least:

```bash
SEC_USER_AGENT="Your Name your@email.com"
POSTGRES_PASSWORD="replace-with-local-secret"
FINEDGAR_AUTH_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
OLLAMA_MODEL=finedgar
```

For local HTTP development:

```text
FINEDGAR_AUTH_COOKIE_SECURE=0
FINEDGAR_EMAIL_MODE=console
FINEDGAR_PUBLIC_BASE_URL=http://localhost:5173
```

For public HTTPS deployments:

```text
FINEDGAR_AUTH_COOKIE_SECURE=1
FINEDGAR_EMAIL_MODE=smtp
FINEDGAR_PUBLIC_BASE_URL=https://your-domain.example
```

## Wrapper Commands

Use `scripts/docker/compose.sh` from the repo root.

```bash
scripts/docker/compose.sh inference up -d
scripts/docker/compose.sh dev up
scripts/docker/compose.sh admin up -d
scripts/docker/compose.sh db up
scripts/docker/compose.sh db migrate
scripts/docker/compose.sh db shell
scripts/docker/compose.sh db logs
scripts/docker/compose.sh data bootstrap -- --limit 3
scripts/docker/compose.sh data index
scripts/docker/compose.sh eval run -- --limit 5
```

The `dev` and `inference` workflows automatically include `docker/compose/db.yml`
alongside their web overlay. Migrations run before the API starts, and
`scripts/docker/compose.sh db migrate` is available for explicit upgrades.

## Services And Compose Files

- `base.yml`: Ollama, shared network, common cache volumes.
- `db.yml`: Postgres 18, `postgres-data`, `db-migrate`.
- `admin.yml`: standalone Dozzle console for live Docker logs.
- `admin.auth.yml`: optional Dozzle simple-auth overlay.
- `inference.yml`: production-style FastAPI plus built React bundle.
- `dev.yml`: reloadable FastAPI plus Vite dev server.
- `data.yml`: data bootstrap and index jobs.
- `eval.yml`: FinanceBench evaluation job.
- `train.nvidia.yml`: CUDA/Unsloth QLoRA training jobs.

Direct Compose equivalent for inference:

```bash
docker compose --project-directory . \
  -f docker/compose/base.yml \
  -f docker/compose/db.yml \
  -f docker/compose/inference.yml \
  up -d
```

## Database Overlay

`db.yml` defines:

- `postgres` from `postgres:18-alpine`
- loopback-only host port `127.0.0.1:${FINEDGAR_POSTGRES_PORT:-5432}:5432`
- `postgres-data:/var/lib/postgresql`
- `pg_isready` healthcheck
- `db-migrate` one-shot Alembic runner

Compose waits for Postgres health before starting web services or migrations.
This follows Docker's `depends_on.condition: service_healthy` behavior.

Open a psql shell:

```bash
scripts/docker/compose.sh db shell
```

Run migrations explicitly:

```bash
scripts/docker/compose.sh db migrate
```

## Backup And Restore

Create a plain SQL backup:

```bash
scripts/docker/compose.sh db up
docker compose --project-directory . \
  -f docker/compose/base.yml \
  -f docker/compose/db.yml \
  exec -T postgres pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" \
  > outputs/finedgar_postgres_backup.sql
```

Restore into an empty database:

```bash
scripts/docker/compose.sh db up
docker compose --project-directory . \
  -f docker/compose/base.yml \
  -f docker/compose/db.yml \
  exec -T postgres psql -U "$POSTGRES_USER" "$POSTGRES_DB" \
  < outputs/finedgar_postgres_backup.sql
```

For local-only reset, stop the stack and remove the named volume:

```bash
scripts/docker/compose.sh inference down
docker volume rm finedgar_postgres-data
```

This deletes users, sessions, verification/reset tokens, conversations, and
messages.

## Inference

```bash
scripts/docker/compose.sh inference up -d
```

Open `http://localhost:8000`.

The `db-migrate` one-shot service runs `alembic upgrade head`. The web service
waits for that job to complete successfully, then starts Uvicorn. If the Ollama
model is already registered in `ollama-data`, `/healthz` should report
`ollama_reachable=true`.

## Development

```bash
scripts/docker/compose.sh dev up
```

Open `http://localhost:5173`. Vite proxies API requests to `web-api-dev`.

Console-mode auth email appears in backend logs:

```bash
scripts/docker/compose.sh dev logs web-api-dev
```

## Admin Console

Start the standalone live-log console:

```bash
scripts/docker/compose.sh admin up -d
```

Open `http://localhost:8081`.

This uses `docker/compose/admin.yml`, a separate Compose project named
`finedgar-admin`. It mounts the Docker socket and filters visible containers to
the main `finedgar` Compose project by default:

```text
FINEDGAR_ADMIN_FILTER=label=com.docker.compose.project=finedgar
```

The console is loopback-only by default:

```text
127.0.0.1:${FINEDGAR_ADMIN_PORT:-8081}:8080
```

Use authenticated mode before exposing it to another machine:

```bash
scripts/docker/compose.sh admin generate-user admin -- \
  --password '<strong-password>' \
  --name 'FinEdgar Admin' \
  --email admin@example.com \
  --user-roles none \
  > docker/admin/users.yml

scripts/docker/compose.sh admin up-auth -d
```

See [docs/admin.md](admin.md) for security notes and troubleshooting.

## Data And Indexing

Bootstrap a small smoke corpus:

```bash
scripts/docker/compose.sh data bootstrap -- --limit 3
```

Build the FAISS index:

```bash
scripts/docker/compose.sh data index
```

Pass script flags after `--`, for example:

```bash
scripts/docker/compose.sh data bootstrap -- --years 2022,2023 --forms 10-K --limit-per-form 1
```

## Evaluation

```bash
scripts/docker/compose.sh eval run
scripts/docker/compose.sh eval run -- --limit 5 --output outputs/eval_runs/eval_docker_smoke.json
```

## NVIDIA Fine-Tuning

Available only on Linux hosts with NVIDIA Container Toolkit configured. The
default training image is:

```text
pytorch/pytorch:2.11.0-cuda13.0-cudnn9-devel
```

Override it from `.env` if needed:

```bash
PYTORCH_IMAGE=pytorch/pytorch:2.11.0-cuda12.8-cudnn9-devel
```

```bash
scripts/docker/compose.sh train check
scripts/docker/compose.sh train prepare
scripts/docker/compose.sh train run
scripts/docker/compose.sh train export
scripts/docker/compose.sh train verify
```

On macOS or CPU-only hosts, training exits before starting:

```text
QLoRA training requires Linux NVIDIA/CUDA.
```

## Troubleshooting

- Missing `.env`: Compose will fail fast for `SEC_USER_AGENT`,
  `POSTGRES_PASSWORD`, or `FINEDGAR_AUTH_SECRET`.
- Port conflict on Postgres: set `FINEDGAR_POSTGRES_PORT=5433`.
- Auth links point to the wrong host: set `FINEDGAR_PUBLIC_BASE_URL`.
- Admin console is empty: confirm `FINEDGAR_ADMIN_FILTER` matches the Compose
  project label on the containers you want to inspect.
- Admin port is already used: set `FINEDGAR_ADMIN_PORT=8082`.
- Browser does not stay logged in on local HTTP: set
  `FINEDGAR_AUTH_COOKIE_SECURE=0`.
- Public deployment does not send email: set `FINEDGAR_EMAIL_MODE=smtp` and all
  `FINEDGAR_SMTP_*` values.
- Migration failure: run `scripts/docker/compose.sh db logs`, then
  `scripts/docker/compose.sh db migrate` after fixing configuration.
- Orphan warning after switching overlays: run the relevant workflow with
  `down --remove-orphans`.
