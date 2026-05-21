# FinEdgar Web

FastAPI + React interface for local SEC filing QA. The web app requires
Postgres-backed login, stores chat history per user, and calls the same
`backend.data.answer_pipeline` used by evaluation scripts.

## Requirements

- Data pipeline artifacts:
  - `data/companies.json`
  - `data/chunks/`
  - `data/xbrl_cache/`
  - `data/vector_index/`
- Ollama reachable from Docker as `http://ollama:11434`.
- Postgres from `docker/compose/db.yml`.
- `.env` values for `SEC_USER_AGENT`, `POSTGRES_PASSWORD`, and
  `FINEDGAR_AUTH_SECRET`.

## Development

Use Docker for the full stack:

```bash
cp .env.example .env
# Edit the required values.
scripts/docker/compose.sh dev up
```

Open `http://localhost:5173`. Vite proxies `/api/*`, `/healthz`, and
`/metrics` to FastAPI.
The wrapper automatically includes the separate database overlay and runs
Alembic migrations before starting the API.

Local email defaults to console mode. Verification and reset links appear in:

```bash
scripts/docker/compose.sh dev logs web-api-dev
```

## Production-Style Local Run

```bash
scripts/docker/compose.sh inference up -d
```

Open `http://localhost:8000`. FastAPI serves the built React bundle and the API
from one origin. For public deployment, put HTTPS in front of the app and set:

```text
FINEDGAR_AUTH_COOKIE_SECURE=1
FINEDGAR_PUBLIC_BASE_URL=https://your-domain.example
FINEDGAR_EMAIL_MODE=smtp
```

## Auth Flow

1. User registers with email and password.
2. Backend stores an Argon2id password hash and creates an email verification
   token.
3. Console or SMTP email provides `/verify-email?token=...`.
4. Verified users can log in.
5. Login stores only a hash of an opaque session token in Postgres and sets an
   HttpOnly `finedgar_session` cookie.
6. Forgot-password sends `/reset-password?token=...`; successful reset rotates
   active sessions.

## Chat History UX

- The left sidebar lists the signed-in user's conversations.
- Asking without a selected conversation creates one automatically.
- Conversations can be created, renamed, selected, and deleted.
- Refreshing the browser reloads the selected conversation from Postgres.
- Users can never read or mutate another user's conversations.

## Admin Interface

Signed-in users can open `http://localhost:5173/admin` in development or
`http://localhost:8000/admin` in production-style local runs. The page shows:

- Ollama reachability, active model, compute mode, indexed company count, and
  XBRL cache status.
- Database counts for users, active sessions, conversations, and messages.
- Data artifact presence for `data/companies.json`, filing chunks, XBRL cache,
  and vector indexes.
- Runtime metadata, including Kubernetes pod, namespace, and node when deployed
  through the Helm chart.
- Recent auth events for local operational debugging.

This is an authenticated operator view, not a full multi-role administration
system. Add explicit admin roles before using it in a multi-user public
deployment.

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---:|---|
| `GET` | `/healthz` | No | Runtime health and Ollama status. |
| `GET` | `/metrics` | No | Prometheus-format HTTP and pipeline metrics. |
| `GET` | `/api/companies` | No | Indexed companies and fiscal years. |
| `GET` | `/api/admin/overview` | Yes | Runtime, data, auth, and deployment overview. |
| `POST` | `/api/auth/register` | No | Create unverified account and send verification. |
| `POST` | `/api/auth/verify-email` | No | Consume verification token. |
| `POST` | `/api/auth/login` | No | Set session cookie. |
| `POST` | `/api/auth/logout` | Yes | Revoke current session. |
| `GET` | `/api/auth/me` | Optional | Return current user or null. |
| `POST` | `/api/auth/forgot-password` | No | Send reset link if account exists. |
| `POST` | `/api/auth/reset-password` | No | Reset password and revoke sessions. |
| `GET` | `/api/conversations` | Yes | List current user's conversations. |
| `POST` | `/api/conversations` | Yes | Create conversation. |
| `PATCH` | `/api/conversations/{id}` | Yes | Rename conversation. |
| `DELETE` | `/api/conversations/{id}` | Yes | Soft-delete conversation. |
| `GET` | `/api/conversations/{id}/messages` | Yes | Load conversation messages. |
| `POST` | `/api/chat` | Yes | Answer question and persist the turn. |

`POST /api/chat` accepts:

```json
{
  "question": "What was Apple's FY2023 revenue?",
  "ticker": "AAPL",
  "years": [2023],
  "conversation_id": null,
  "route_override": null
}
```

It returns the normal answer payload plus `conversation_id` and `message_id`.

## Cookie And Session Settings

- Cookie name: `finedgar_session`
- `HttpOnly`: always enabled
- `SameSite`: `Lax`
- `Secure`: controlled by `FINEDGAR_AUTH_COOKIE_SECURE`
- Session TTL: `FINEDGAR_SESSION_DAYS`

For local HTTP testing use `FINEDGAR_AUTH_COOKIE_SECURE=0`. For public HTTPS
deployments use `1`.

## Compute Mode

The web app defaults to CPU mode:

```text
FINEDGAR_FORCE_CPU=1
```

Set `FINEDGAR_FORCE_CPU=0` to allow automatic GPU behavior. The health endpoint
reports the active mode.

## Layout

```text
webapp/
  backend/
    db.py
    db_models.py
    migrations/
    routes/
      auth.py
      chat.py
      companies.py
      conversations.py
      health.py
    services/
      auth.py
      companies.py
      conversations.py
      pipeline.py
    schemas.py
  frontend/
    src/
      App.tsx
      api.ts
      components/
      styles.css
```

## Status

- Non-streaming chat is implemented.
- Postgres-backed user chat history is implemented.
- Email/password authentication is implemented.
- Authenticated admin overview UI is implemented.
- Token streaming, OAuth/OIDC, admin roles, and team/organization support are
  not implemented.
