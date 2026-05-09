from __future__ import annotations

import os
import sys
from pathlib import Path

# Default the webapp to CPU/RAM-only inference — matches the privacy /
# mobile-plausible story. Users who want GPU can set FINEDGAR_FORCE_CPU=0
# in the environment before launching uvicorn. Must be set before any
# backend.data.* import because the embedding and reranker models read
# it at first-load time.
os.environ.setdefault("FINEDGAR_FORCE_CPU", "1")

from contextlib import asynccontextmanager  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi import Request  # noqa: E402
from fastapi.responses import FileResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.observability import (  # noqa: E402
    monotonic_seconds,
    observe_http,
    render_metrics,
    setup_opentelemetry,
)
from .db import dispose_db  # noqa: E402
from .routes.admin import router as admin_router  # noqa: E402
from .routes.auth import router as auth_router  # noqa: E402
from .routes.chat import router as chat_router  # noqa: E402
from .routes.companies import router as companies_router  # noqa: E402
from .routes.conversations import router as conversations_router  # noqa: E402
from .routes.health import router as health_router  # noqa: E402

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        yield
    finally:
        await dispose_db()


app = FastAPI(
    title="FinEdgar Web",
    description="Local chat app over SEC filings. All compute stays on-device.",
    version="0.1.0",
    lifespan=lifespan,
)

# Dev-only CORS: Vite runs on :5173, FastAPI on :8000. Production serves the
# built bundle from the same origin, so this is a no-op there.
allow_origins = os.getenv(
    "FINEDGAR_ALLOW_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173",
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in allow_origins if o.strip()],
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _metrics_middleware(request: Request, call_next):
    start = monotonic_seconds()
    response = None
    try:
        response = await call_next(request)
        return response
    finally:
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        status_code = response.status_code if response is not None else 500
        observe_http(request.method, path, status_code, monotonic_seconds() - start)


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    payload, content_type = render_metrics()
    return Response(content=payload, media_type=content_type)


setup_opentelemetry(app)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(companies_router)
app.include_router(conversations_router)
app.include_router(chat_router)


# In production (after `npm run build`), serve the React bundle from /.
if FRONTEND_DIST.is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_DIST / "assets"),
        name="assets",
    )

    @app.get("/")
    def _index() -> FileResponse:
        return FileResponse(FRONTEND_DIST / "index.html")

    @app.get("/{_path:path}")
    def _spa_fallback(_path: str) -> FileResponse:
        # Route everything the SPA renders client-side back to index.html.
        return FileResponse(FRONTEND_DIST / "index.html")
