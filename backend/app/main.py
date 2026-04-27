"""FastAPI application entry point.

The heavy lifting lives in sibling modules:

* ``store``         — sessions, ring buffer, pub/sub singletons.
* ``api_routes``    — REST + WebSocket router.
* ``observability`` — logging, /metrics, enriched /api/health, request tracing.
* ``config``        — pydantic-settings ``Settings``.

This file just wires them together.
"""

from __future__ import annotations

import logging
import sys
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
from service.etw_cleanup import sweep_orphan_sessions  # noqa: E402

logger = logging.getLogger("activity_tracker")


def create_app() -> FastAPI:
    """Build and configure the FastAPI app. Importable for tests."""
    observability.configure_logging()

    app = FastAPI(title="Activity Tracker", version="0.3.0")

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

    @app.on_event("startup")
    def _on_startup() -> None:
        try:
            stopped = sweep_orphan_sessions()
            if stopped:
                logger.info("swept orphan ETW sessions", extra={"sessions": stopped})
        except Exception as exc:  # noqa: BLE001
            logger.warning("orphan sweep failed: %s", exc)

    @app.on_event("shutdown")
    def _on_shutdown() -> None:
        try:
            store.shutdown()
        except Exception as exc:  # noqa: BLE001
            logger.warning("store shutdown failed: %s", exc)

    return app


app = create_app()
