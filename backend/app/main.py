"""FastAPI application entry point.

The heavy lifting lives in sibling modules:

* ``store``         — sessions, ring buffer, pub/sub singletons.
* ``api_routes``    — REST + WebSocket router.
* ``observability`` — logging, /metrics, enriched /api/health, request tracing.
* ``config``        — pydantic-settings ``Settings``.

This file just wires them together.
"""

from __future__ import annotations

import contextlib
import logging
import sys
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Repo root must be on sys.path so ``import service.*`` works regardless of
# the cwd uvicorn was launched from.
BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backend.app import api_routes, observability  # noqa: E402
from backend.app.store import store  # noqa: E402

logger = logging.getLogger("activity_tracker")


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Replaces the deprecated ``@app.on_event`` decorators.

    Startup work goes before ``yield``, shutdown work after. FastAPI 0.116+
    raises a deprecation warning for the old API and is expected to remove
    it altogether in a future minor — using ``lifespan`` keeps us forward-
    compatible without code changes when we bump the version.
    """
    yield
    try:
        store.shutdown()
    except OSError as exc:
        logger.warning("store shutdown failed: %s", exc)


def create_app() -> FastAPI:
    """Build and configure the FastAPI app. Importable for tests."""
    observability.configure_logging()

    app = FastAPI(
        title="Activity Tracker",
        version="0.3.0",
        lifespan=lifespan,
    )

    # Middleware order: Starlette wraps each successive add_middleware call
    # OUTSIDE the previous one, so the LAST registered middleware runs
    # OUTERMOST per request. Register CORS first; RequestTraceMiddleware ends
    # up outermost and tags every response (including CORS preflights) with
    # X-Trace-Id.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=observability.cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(observability.RequestTraceMiddleware)

    # Mount /assets if the UI was built.
    assets_dir = api_routes.STATIC_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    # Observability router carries /metrics + the enriched /api/health, so
    # include it BEFORE api_routes (whose duplicate /api/health was removed).
    app.include_router(observability.router)
    app.include_router(api_routes.router)

    # Orphan ETW session cleanup runs inside the native binary itself
    # (service/native/src/etw_session.cpp::SweepOrphans).

    return app


app = create_app()
