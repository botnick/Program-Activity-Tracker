from __future__ import annotations

import asyncio
import json
import logging
import sys
import uuid
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from service.capture_service import CaptureService, CaptureTarget, is_admin  # noqa: E402

logger = logging.getLogger("activity_tracker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


EVENT_RING_SIZE = 50_000
SUBSCRIBER_QUEUE_SIZE = 4096


class ProcessSelectRequest(BaseModel):
    exe_path: str | None = Field(default=None)
    pid: int | None = Field(default=None)


class SessionResponse(BaseModel):
    session_id: str
    exe_path: str
    pid: int
    created_at: str
    status: str
    capture: str
    capture_error: str | None = None


@dataclass
class ActivityEvent:
    id: str
    session_id: str
    timestamp: str
    kind: str
    pid: int | None = None
    ppid: int | None = None
    path: str | None = None
    target: str | None = None
    operation: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, Any]] = {}
        self._events: dict[str, deque[ActivityEvent]] = defaultdict(
            lambda: deque(maxlen=EVENT_RING_SIZE)
        )
        self._capture: dict[str, CaptureService] = {}

    def create(
        self,
        exe_path: str,
        pid: int,
        capture_status: str,
        capture_error: str | None,
    ) -> dict[str, Any]:
        session_id = str(uuid.uuid4())
        session = {
            "session_id": session_id,
            "exe_path": exe_path,
            "pid": pid,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "tracking" if capture_status == "live" else capture_status,
            "capture": capture_status,
            "capture_error": capture_error,
        }
        self._sessions[session_id] = session
        return session

    def attach_capture(self, session_id: str, service: CaptureService) -> None:
        self._capture[session_id] = service

    def detach_capture(self, session_id: str) -> CaptureService | None:
        return self._capture.pop(session_id, None)

    def get(self, session_id: str) -> dict[str, Any] | None:
        return self._sessions.get(session_id)

    def list(self) -> list[dict[str, Any]]:
        return list(self._sessions.values())

    def add_event(self, event: ActivityEvent) -> None:
        self._events[event.session_id].append(event)

    def events(self, session_id: str) -> list[ActivityEvent]:
        return list(self._events[session_id])

    def all_capture_services(self) -> list[CaptureService]:
        return list(self._capture.values())


class EventHub:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)

    def subscribe(self, session_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_SIZE)
        self._subscribers[session_id].add(queue)
        return queue

    def unsubscribe(self, session_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers[session_id].discard(queue)

    async def publish(self, session_id: str, payload: dict[str, Any]) -> None:
        dead: list[asyncio.Queue[dict[str, Any]]] = []
        for queue in self._subscribers[session_id]:
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                dead.append(queue)
        for queue in dead:
            self._subscribers[session_id].discard(queue)


app = FastAPI(title="Activity Tracker", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = BASE_DIR / "ui" / "dist"
store = SessionStore()
hub = EventHub()

if STATIC_DIR.exists():
    assets_dir = STATIC_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")


# ---- helpers ---------------------------------------------------------------

def _resolve_target(req: ProcessSelectRequest) -> tuple[int, str]:
    """Turn a request (pid or exe_path) into (pid, resolved_exe_path)."""
    if req.pid is not None:
        try:
            proc = psutil.Process(req.pid)
            exe = proc.exe() or req.exe_path or proc.name()
            return req.pid, exe
        except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            raise HTTPException(status_code=404, detail=f"pid {req.pid}: {exc}") from exc

    if not req.exe_path:
        raise HTTPException(status_code=400, detail="provide either pid or exe_path")

    target_path = Path(req.exe_path)
    target_name = target_path.name.lower()
    matches: list[psutil.Process] = []
    for proc in psutil.process_iter(["pid", "name", "exe"]):
        try:
            exe = (proc.info.get("exe") or "").lower()
            name = (proc.info.get("name") or "").lower()
            if exe and Path(exe) == target_path:
                matches.append(proc)
            elif name == target_name:
                matches.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not matches:
        raise HTTPException(
            status_code=404,
            detail=f"no running process matches {req.exe_path}",
        )
    proc = matches[0]
    return proc.pid, proc.info.get("exe") or req.exe_path


def _make_event_callback(loop: asyncio.AbstractEventLoop, session_id: str):
    """Build the sync callback that capture_service hands events to (on its thread)."""
    def callback(payload: dict[str, Any]) -> None:
        event = ActivityEvent(
            id=str(uuid.uuid4()),
            session_id=session_id,
            timestamp=payload.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            kind=payload.get("kind", "unknown"),
            pid=payload.get("pid"),
            ppid=payload.get("ppid"),
            path=payload.get("path"),
            target=payload.get("target"),
            operation=payload.get("operation"),
            details=payload.get("details") or {},
        )
        store.add_event(event)
        try:
            asyncio.run_coroutine_threadsafe(
                hub.publish(session_id, asdict(event)), loop
            )
        except RuntimeError:
            pass

    return callback


# ---- routes ----------------------------------------------------------------

@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "admin": is_admin()}


@app.get("/api/processes")
def list_processes() -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for proc in psutil.process_iter(["pid", "name", "exe", "username", "ppid"]):
        try:
            info = proc.info
            items.append(
                {
                    "pid": info.get("pid"),
                    "ppid": info.get("ppid"),
                    "name": info.get("name"),
                    "exe": info.get("exe"),
                    "username": info.get("username"),
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    items.sort(key=lambda x: (x.get("name") or "").lower())
    return {"items": items, "admin": is_admin()}


@app.post("/api/sessions", response_model=SessionResponse)
async def create_session(request: ProcessSelectRequest) -> SessionResponse:
    pid, exe_path = _resolve_target(request)

    if not is_admin():
        session = store.create(
            exe_path=exe_path,
            pid=pid,
            capture_status="needs_admin",
            capture_error="Backend is not Administrator; ETW capture disabled.",
        )
        return SessionResponse(**session)

    # Reserve the session id first so the capture callback can publish to it
    # from the very first event.
    session = store.create(
        exe_path=exe_path,
        pid=pid,
        capture_status="initializing",
        capture_error=None,
    )
    session_id = session["session_id"]

    loop = asyncio.get_running_loop()
    service = CaptureService(
        target=CaptureTarget(exe_path=exe_path, pid=pid),
        on_event=_make_event_callback(loop, session_id),
    )
    try:
        service.start()
    except PermissionError as exc:
        session["capture"] = "needs_admin"
        session["status"] = "needs_admin"
        session["capture_error"] = str(exc)
        return SessionResponse(**session)
    except Exception as exc:  # noqa: BLE001
        logger.exception("failed to start capture")
        session["capture"] = "failed"
        session["status"] = "failed"
        session["capture_error"] = f"{type(exc).__name__}: {exc}"
        return SessionResponse(**session)

    store.attach_capture(session_id, service)
    session["capture"] = "live"
    session["status"] = "tracking"
    return SessionResponse(**session)


@app.delete("/api/sessions/{session_id}")
def stop_session(session_id: str) -> dict[str, str]:
    if store.get(session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    service = store.detach_capture(session_id)
    if service is not None:
        service.stop()
    session = store.get(session_id)
    if session is not None:
        session["status"] = "stopped"
        session["capture"] = "stopped"
    return {"status": "stopped"}


@app.get("/api/sessions")
def list_sessions() -> dict[str, list[dict[str, Any]]]:
    return {"items": store.list()}


@app.get("/api/sessions/{session_id}/events")
def get_events(session_id: str) -> dict[str, list[dict[str, Any]]]:
    if store.get(session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    return {"items": [asdict(event) for event in store.events(session_id)]}


@app.post("/api/sessions/{session_id}/emit")
async def emit_event(session_id: str, payload: dict[str, Any]) -> dict[str, str]:
    if store.get(session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    event = ActivityEvent(
        id=str(uuid.uuid4()),
        session_id=session_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        kind=payload.get("kind", "custom"),
        pid=payload.get("pid"),
        ppid=payload.get("ppid"),
        path=payload.get("path"),
        target=payload.get("target"),
        operation=payload.get("operation"),
        details=payload.get("details", {}),
    )
    store.add_event(event)
    await hub.publish(session_id, asdict(event))
    return {"status": "accepted"}


@app.websocket("/ws/sessions/{session_id}")
async def stream_session(websocket: WebSocket, session_id: str) -> None:
    if store.get(session_id) is None:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    queue = hub.subscribe(session_id)
    try:
        for event in store.events(session_id):
            await websocket.send_text(json.dumps(asdict(event)))
        while True:
            payload = await queue.get()
            await websocket.send_text(json.dumps(payload))
    except WebSocketDisconnect:
        pass
    finally:
        hub.unsubscribe(session_id, queue)


@app.on_event("shutdown")
def _shutdown_capture() -> None:
    for service in store.all_capture_services():
        try:
            service.stop()
        except Exception as exc:  # noqa: BLE001
            logger.warning("capture stop on shutdown failed: %s", exc)


@app.get("/")
def index() -> FileResponse:
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="ui not built")
    return FileResponse(index_file)
