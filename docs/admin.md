# Admin Interfaces

FinEdgar now has two complementary admin surfaces:

- An in-app authenticated operator dashboard at `/admin`.
- An optional standalone Dozzle console for live Docker log monitoring.

The in-app dashboard is the default place to check whether the application is
usable. Dozzle is the lower-level tool for container logs and Docker state.

## In-App Admin Dashboard

Open the app and sign in, then go to:

```text
http://localhost:5173/admin
```

For production-style local runs:

```text
http://localhost:8000/admin
```

For the k3d Kubernetes lab:

```text
http://finedgar.localhost/admin
```

The dashboard is backed by:

```text
GET /api/admin/overview
```

## What It Shows

- System state: Ollama reachability, active model, indexed companies, XBRL cache,
  compute mode, users, active sessions, conversations, and messages.
- Runtime metadata: environment, release, Kubernetes pod, namespace, and node.
- Data artifacts: companies catalog, filing chunks, XBRL cache, and vector
  indexes.
- Recent auth events: useful while debugging registration, verification, login,
  logout, and reset-password flows.
- Direct links to `/healthz` and `/metrics`.

The design is intentionally operational rather than decorative. It prioritizes
the questions an operator asks during local deployment work:

- Is the app healthy enough to use?
- Is the model server reachable?
- Is the SEC filing corpus mounted and indexed?
- Is auth/session state being written to Postgres?
- Am I running locally, in Docker, or inside Kubernetes?

## Access Model

`/admin` and `/api/admin/overview` require a valid FinEdgar session. The current
application does not have admin roles yet, so every authenticated user can open
the operator dashboard. This is acceptable for the local portfolio/lab workflow
where the deployment is single-user or trusted.

Before exposing the app to untrusted users, add:

- An `is_admin` or role table in the auth model.
- Backend authorization checks on `/api/admin/*`.
- UI hiding for non-admin users.
- Audit logging for admin-only actions if mutation endpoints are added later.

## Dashboard Design Rationale

The dashboard follows current admin/dashboard guidance:

- Start from operator tasks, not database tables.
- Keep the first view glanceable with a small set of high-signal metrics.
- Show context for every status instead of raw numbers alone.
- Group runtime, data, and auth state separately.
- Use progressive detail: summary cards first, tables and artifact rows below.

This keeps the page useful for the Kubernetes learning track without turning it
into a generic analytics dashboard.

## Standalone Docker Log Console

FinEdgar also includes an optional admin console for live Docker log monitoring.
The implementation uses Dozzle because it is focused on real-time Docker logs,
container health, search, and lightweight monitoring without adding a database
or a larger observability stack.

## What Dozzle Provides

- Live logs for the FinEdgar Compose project.
- Container status and basic resource visibility.
- Browser search over recent logs.
- A standalone Compose project named `finedgar-admin`.
- Loopback-only access by default at `http://localhost:8081`.

The console is intentionally independent from the app stack. You can start,
stop, or upgrade it without restarting Postgres, Ollama, or the web app.

## Start The Local Console

```bash
scripts/docker/compose.sh admin up -d
```

Open:

```text
http://localhost:8081
```

Check status and logs:

```bash
scripts/docker/compose.sh admin ps
scripts/docker/compose.sh admin logs
```

Stop it:

```bash
scripts/docker/compose.sh admin down
```

## Filtering

By default the console only shows containers with:

```text
label=com.docker.compose.project=finedgar
```

That means it monitors the main FinEdgar stack while leaving unrelated Docker
containers out of view. Override the filter only when needed:

```bash
FINEDGAR_ADMIN_FILTER="name=finedgar-web-api-1" scripts/docker/compose.sh admin up -d
```

To see all local Docker containers, set an empty filter:

```bash
FINEDGAR_ADMIN_FILTER= scripts/docker/compose.sh admin up -d
```

## Authenticated Mode

Loopback-only mode is fine for local testing. For anything reachable from
another machine, enable auth or put the console behind an authenticated HTTPS
reverse proxy.

Generate a Dozzle users file:

```bash
scripts/docker/compose.sh admin generate-user admin -- \
  --password '<strong-password>' \
  --name 'FinEdgar Admin' \
  --email admin@example.com \
  --user-roles none \
  > docker/admin/users.yml
```

Start with the auth overlay:

```bash
scripts/docker/compose.sh admin up-auth -d
```

`docker/admin/users.yml` should stay local and uncommitted. The committed
`docker/admin/users.example.yml` shows the shape of the file.

## Security Notes

- The admin console mounts `/var/run/docker.sock`. Access to that socket is
  highly privileged even when the bind mount is read-only.
- Do not expose `FINEDGAR_ADMIN_PORT` on `0.0.0.0` without HTTPS and auth.
- Logs can contain local verification links, password reset links, stack traces,
  request metadata, or operational secrets accidentally printed by dependencies.
- Container actions and shell access are disabled by default with
  `FINEDGAR_ADMIN_ENABLE_ACTIONS=false` and
  `FINEDGAR_ADMIN_ENABLE_SHELL=false`.
- Keep console-email auth links local. In public deployments, prefer SMTP and
  avoid printing secrets to logs.

## Useful Commands

```bash
scripts/docker/compose.sh admin config
scripts/docker/compose.sh admin ps
scripts/docker/compose.sh admin logs --tail 100 -f
scripts/docker/compose.sh admin down
```

## Troubleshooting

- Empty console: confirm the main stack is running with
  `scripts/docker/compose.sh inference ps` or `scripts/docker/compose.sh dev ps`.
- Still empty: check `FINEDGAR_ADMIN_FILTER`. The default assumes the app stack
  uses Compose project name `finedgar`.
- Port conflict: set `FINEDGAR_ADMIN_PORT=8082`.
- Auth mode fails to start: create `docker/admin/users.yml` with
  `scripts/docker/compose.sh admin generate-user`.
