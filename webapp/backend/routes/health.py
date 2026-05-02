"""Health endpoint for local, Docker, and Kubernetes deployments."""

from __future__ import annotations

import os
from pathlib import Path

import httpx
from fastapi import APIRouter

from ..schemas import Health
from ..services.companies import load_companies

router = APIRouter()

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "finedgar")
REPO_ROOT = Path(__file__).resolve().parents[3]
XBRL_CACHE = REPO_ROOT / "data" / "xbrl_cache"


@router.get("/healthz", response_model=Health)
def healthz() -> Health:
    try:
        with httpx.Client(timeout=2.0) as c:
            r = c.get(f"{OLLAMA_HOST}/api/tags")
            r.raise_for_status()
            ollama_ok = True
    except Exception:
        ollama_ok = False

    force_cpu = os.getenv("FINEDGAR_FORCE_CPU", "0").lower() in {"1", "true", "yes"}
    return Health(
        ollama_reachable=ollama_ok,
        ollama_host=OLLAMA_HOST,
        ollama_model=OLLAMA_MODEL,
        indexed_companies=len(load_companies()),
        xbrl_cache_warm=XBRL_CACHE.is_dir() and any(XBRL_CACHE.glob("*.json")),
        compute_mode="cpu" if force_cpu else "auto",
    )
