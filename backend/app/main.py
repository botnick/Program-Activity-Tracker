"""FastAPI application entry point.

The heavy lifting lives in sibling modules:

* ``store``         — sessions, ring buffer, pub/sub singletons.
* ``api_routes``    — REST + WebSocket router.
* ``observability`` — logging hook + (future) /metrics router.
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

# Repo root must be on sys.path so ``import service.capture_service`` works
# regardless of the cwd uvicorn was launched from.
BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backend.app import api_routes, observability  # noqa: E402
from backend.app.store import store  # noqa: E402

observability.configure_logging()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(title="Activity Tracker", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Agent C will lock this down.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_assets_dir = api_routes.STATIC_DIR / "assets"
if _assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=_assets_dir), name="assets")

app.include_router(api_routes.router)
app.include_router(observability.router)


@app.on_event("shutdown")
def _shutdown_capture() -> None:
    store.shutdown()
