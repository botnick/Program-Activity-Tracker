"""Observability: structured logging, request tracing, /metrics, /api/health.

Owned by Agent C. Exposes:

* ``configure_logging()`` — idempotent stdlib-only logging setup with a console
  handler (human-readable) and a rotating JSON file handler under
  ``<repo_root>/logs/`` (or ``settings.log_dir``).
* ``RequestTraceMiddleware`` — assigns / propagates ``X-Trace-Id`` per request
  and emits a structured ``request`` log line with method/path/status/duration.
* ``router`` — FastAPI ``APIRouter`` carrying ``GET /metrics`` and the enriched
  ``GET /api/health``. The latter shadows the basic health route in
  ``api_routes.py``; Agent E will remove the duplicate at integration.
* ``cors_origins()`` — returns the configured allowlist; ``main.py`` will pass
  this to ``CORSMiddleware`` instead of the current ``allow_origins=["*"]``.
* ``is_safe_exe_path()`` — path-traversal guard used by ``_resolve_target``.
* ``observe_event`` / ``observe_dropped`` / ``observe_request`` /
  ``update_capture_gauges`` — Prometheus instrumentation hooks; all are no-ops
  when ``prometheus-client`` is not installed.

No third-party logging libraries are used; the JSON formatter is a small
``logging.Formatter`` subclass writing one JSON object per line.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import logging.handlers
import re
import time
import uuid
from collections.abc import Iterable
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from backend.app.config import get_settings

# ---- module state ----------------------------------------------------------

_started_at: float = time.monotonic()

#: Per-request trace id. The middleware sets it; the JSON formatter reads it.
_trace_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "tracker_trace_id", default=None
)

# Sentinel attribute on the root logger that signals configure_logging() has
# already wired its handlers; we use it to keep the call idempotent.
_CONFIGURED_ATTR = "_tracker_logging_configured"

# Repo root: backend/app/observability.py -> parents[2]
_BASE_DIR = Path(__file__).resolve().parents[2]
BASE_DIR = _BASE_DIR  # public alias for callers that want a non-private name


# Stream name -> on-disk filename. Used by both the live-tail endpoints and
# the registered handler attachments below.
LOG_STREAM_FILENAMES: dict[str, str] = {
    "tracker": "tracker.log",
    "events": "events.log",
    "requests": "requests.log",
    "errors": "errors.log",
    "native": "native.log",
}


# ---- trace id --------------------------------------------------------------

def get_trace_id() -> str | None:
    return _trace_id_var.get()


def set_trace_id(value: str | None) -> contextvars.Token[str | None]:
    return _trace_id_var.set(value)


# ---- JSON log formatter ----------------------------------------------------

class JsonFormatter(logging.Formatter):
    """Emit one JSON object per record.

    Always includes ``ts``, ``level``, ``logger``, ``message``. Any extras
    attached via ``logger.info("...", extra={...})`` are merged in. The active
    ``trace_id`` contextvar is included when present.
    """

    _RESERVED = {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "message", "asctime", "taskName",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        trace_id = get_trace_id()
        if trace_id:
            payload["trace_id"] = trace_id
        # Merge user-supplied extras (those not in the reserved LogRecord set).
        for key, value in record.__dict__.items():
            if key in self._RESERVED or key.startswith("_"):
                continue
            if key in payload:
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = repr(value)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


# ---- logging setup ---------------------------------------------------------

def _resolve_log_dir() -> Path:
    settings = get_settings()
    raw = Path(settings.log_dir)
    if raw.is_absolute():
        return raw
    return _BASE_DIR / raw


def _attach_stream_handler(
    name: str,
    filename: str,
    log_dir: Path,
    level: int = logging.INFO,
    formatter: logging.Formatter | None = None,
) -> None:
    """Attach a RotatingFileHandler to a named logger.

    The handler is exclusive: the named logger's handlers are wiped first
    so re-running configure_logging() doesn't double up.
    """
    lg = logging.getLogger(name)
    for existing in list(lg.handlers):
        with contextlib.suppress(Exception):
            existing.close()
        lg.removeHandler(existing)
    lg.setLevel(level)
    handler = RotatingFileHandler(
        log_dir / filename,
        maxBytes=50 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(formatter or JsonFormatter())
    lg.addHandler(handler)
    # Don't propagate to root, so these lines don't double-log into tracker.log.
    lg.propagate = False


class _ErrorsTeeHandler(logging.Handler):
    """Forward WARNING+ records on the root logger into the errors stream.

    Skips records that already originate from the errors logger to avoid an
    emit -> handle -> emit loop.
    """

    def __init__(self, target: logging.Logger) -> None:
        super().__init__(level=logging.WARNING)
        self._target = target

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith(self._target.name):
            return
        self._target.handle(record)


def configure_logging() -> None:
    """Wire up console + rotating JSON file logging.

    Idempotent: subsequent calls return without adding duplicate handlers.
    """
    root = logging.getLogger()
    if getattr(root, _CONFIGURED_ATTR, False):
        return

    settings = get_settings()
    level_name = (settings.log_level or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    log_dir = _resolve_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "tracker.log"

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )

    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=100 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(JsonFormatter())

    root.setLevel(level)
    root.addHandler(console_handler)
    root.addHandler(file_handler)

    # Named-stream routed handlers — each named logger writes exclusively to
    # its own file with `propagate=False` so output doesn't double-log into
    # tracker.log.
    _attach_stream_handler("activity_tracker.events", "events.log", log_dir)
    _attach_stream_handler("activity_tracker.request", "requests.log", log_dir)
    _attach_stream_handler(
        "activity_tracker.errors", "errors.log", log_dir, level=logging.WARNING
    )
    _attach_stream_handler("activity_tracker.native", "native.log", log_dir)

    # Tee any WARNING+ from the root logger (i.e. from any module that
    # propagates to root) into the errors stream too.
    errors_logger = logging.getLogger("activity_tracker.errors")
    root.addHandler(_ErrorsTeeHandler(errors_logger))

    # The dedicated app logger inherits handlers from root; ensure level only.
    tracker_logger = logging.getLogger("activity_tracker")
    tracker_logger.setLevel(level)

    setattr(root, _CONFIGURED_ATTR, True)

    tracker_logger.info("logging configured (path=%s level=%s)", log_path, level_name)


# ---- log stream helpers (file enumeration + tail) --------------------------

def list_log_streams() -> list[dict[str, Any]]:
    """Return one entry per known log stream with its on-disk path + size.

    Files that don't exist yet are still listed so the UI can show all five
    streams even before the backend has logged anything.
    """
    log_dir = _resolve_log_dir()
    streams: list[dict[str, Any]] = []
    for name, filename in LOG_STREAM_FILENAMES.items():
        p = log_dir / filename
        try:
            size = p.stat().st_size if p.exists() else 0
        except OSError:
            size = 0
        streams.append(
            {
                "name": name,
                "path": str(p),
                "size": size,
                "exists": p.exists(),
            }
        )
    return streams


def read_log_tail(stream: str, tail: int = 200) -> list[dict[str, Any]]:
    """Return the last ``tail`` JSON-decoded lines of ``stream``.

    Lines that aren't valid JSON are returned as ``{"message": ..., "raw": True}``
    so the UI can still render them. Unknown stream names yield ``[]``.
    """
    filename = LOG_STREAM_FILENAMES.get(stream)
    if not filename:
        return []
    log_dir = _resolve_log_dir()
    p = log_dir / filename
    if not p.exists():
        return []
    items: list[dict[str, Any]] = []
    try:
        with p.open("rb") as f:
            f.seek(0, 2)
            end = f.tell()
            chunk = 64 * 1024
            buf = b""
            pos = end
            while pos > 0 and buf.count(b"\n") <= tail:
                read = min(chunk, pos)
                pos -= read
                f.seek(pos)
                buf = f.read(read) + buf
            lines = buf.splitlines()[-tail:]
        for raw in lines:
            text = raw.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            try:
                items.append(json.loads(text))
            except (ValueError, json.JSONDecodeError):
                items.append({"message": text, "raw": True})
    except OSError as exc:
        logging.getLogger("activity_tracker").warning(
            "read_log_tail(%s): %s", stream, exc
        )
    return items


# ---- request middleware ----------------------------------------------------

class RequestTraceMiddleware(BaseHTTPMiddleware):
    """Per-request trace id + structured access log.

    * Honors an inbound ``X-Trace-Id`` (truncated to 64 chars) when present;
      otherwise generates a 12-hex-char id.
    * Sets the contextvar so log lines emitted during the request are tagged.
    * After the call, emits a single ``request`` INFO log with method, path,
      status_code, duration_ms and trace_id, and observes the histogram.
    * Adds ``X-Trace-Id`` to the response.
    """

    _logger = logging.getLogger("activity_tracker.request")

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        incoming = request.headers.get("x-trace-id")
        trace_id = incoming[:64] if incoming else uuid.uuid4().hex[:12]

        token = set_trace_id(trace_id)
        start = time.monotonic()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            duration_ms = (time.monotonic() - start) * 1000.0
            self._logger.exception(
                "request failed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": 500,
                    "duration_ms": round(duration_ms, 3),
                    "trace_id": trace_id,
                },
            )
            observe_request(request.url.path, (time.monotonic() - start))
            raise
        finally:
            _trace_id_var.reset(token)

        duration_seconds = time.monotonic() - start
        duration_ms = duration_seconds * 1000.0
        self._logger.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": status_code,
                "duration_ms": round(duration_ms, 3),
                "trace_id": trace_id,
            },
        )
        observe_request(request.url.path, duration_seconds)

        response.headers["X-Trace-Id"] = trace_id
        return response


# ---- CORS ------------------------------------------------------------------

def cors_origins() -> list[str]:
    """Allowlist for ``CORSMiddleware`` — populated from ``Settings``."""
    return list(get_settings().cors_origins)


# ---- path validator --------------------------------------------------------

_DRIVE_RE = re.compile(r"^[A-Za-z]:$")


def is_safe_exe_path(path: str) -> bool:
    """Return True iff ``path`` is an absolute, drive-anchored Windows path
    with no parent-traversal segments after normalization.

    Rejects: empty strings, UNC paths (``\\\\server\\share\\...``), POSIX-style
    absolute paths (``/etc/passwd``), and anything containing a literal ``..``
    component.
    """
    if not path or not isinstance(path, str):
        return False
    try:
        p = Path(path)
    except (TypeError, ValueError):
        return False
    if not p.is_absolute():
        return False
    parts = p.parts
    if not parts:
        return False
    first = parts[0]
    # Path on Windows treats "C:\\foo" as parts=("C:\\", "foo"); strip a trailing
    # backslash so the regex matches "C:".
    first_clean = first.rstrip("\\/")
    if not _DRIVE_RE.match(first_clean):
        return False
    if any(seg == ".." for seg in parts):
        return False
    # Defensive: reject literal ".." substrings that survived normalization.
    return ".." not in path.replace("\\", "/").split("/")


# ---- Prometheus metrics (optional dependency) ------------------------------

try:  # pragma: no cover - exercised by import-time presence/absence
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )
    _PROMETHEUS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PROMETHEUS_AVAILABLE = False
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"  # type: ignore[assignment]
    generate_latest = None  # type: ignore[assignment]


if _PROMETHEUS_AVAILABLE:
    _events_total = Counter(
        "tracker_events_total",
        "Total ETW/capture events observed, partitioned by kind.",
        ["kind"],
    )
    _events_dropped_total = Counter(
        "tracker_events_dropped_total",
        "Total events dropped due to subscriber backpressure.",
    )
    _capture_errors_total = Counter(
        "tracker_capture_errors_total",
        "Total errors raised inside the capture pipeline.",
    )
    _sessions_live = Gauge(
        "tracker_capture_sessions_live",
        "Number of capture sessions currently attached.",
    )
    _subscribers_gauge = Gauge(
        "tracker_subscribers",
        "Number of WebSocket subscribers across all sessions.",
    )
    _file_object_cache_gauge = Gauge(
        "tracker_file_object_cache_size",
        "Aggregate FileObject->path LRU size across capture services.",
    )
    _tracked_pids_gauge = Gauge(
        "tracker_tracked_pids_total",
        "Aggregate tracked PID count across capture services.",
    )
    _request_duration = Histogram(
        "tracker_request_duration_seconds",
        "HTTP request latency, partitioned by path.",
        ["path"],
        buckets=(0.005, 0.025, 0.1, 0.5, 2.5),
    )
else:
    _events_total = None
    _events_dropped_total = None
    _capture_errors_total = None
    _sessions_live = None
    _subscribers_gauge = None
    _file_object_cache_gauge = None
    _tracked_pids_gauge = None
    _request_duration = None


def observe_event(kind: str) -> None:
    if _events_total is not None:
        _events_total.labels(kind=kind).inc()


def observe_dropped(n: int) -> None:
    if _events_dropped_total is not None and n:
        _events_dropped_total.inc(n)


def observe_capture_error(n: int = 1) -> None:
    if _capture_errors_total is not None and n:
        _capture_errors_total.inc(n)


def observe_request(path: str, duration_seconds: float) -> None:
    if _request_duration is not None:
        _request_duration.labels(path=path).observe(duration_seconds)


def update_capture_gauges(stats_iter: Iterable[dict[str, Any]]) -> None:
    """Set capture-related gauges from the iterable of ``stats()`` dicts."""
    if not _PROMETHEUS_AVAILABLE:
        return
    sessions = 0
    cache_total = 0
    pids_total = 0
    for stats in stats_iter:
        sessions += 1
        with contextlib.suppress(TypeError, ValueError):
            cache_total += int(stats.get("file_object_cache_size") or 0)
        with contextlib.suppress(TypeError, ValueError):
            pids_total += int(stats.get("tracked_pids") or 0)
    if _sessions_live is not None:
        _sessions_live.set(sessions)
    if _file_object_cache_gauge is not None:
        _file_object_cache_gauge.set(cache_total)
    if _tracked_pids_gauge is not None:
        _tracked_pids_gauge.set(pids_total)


def _set_subscribers_gauge(count: int) -> None:
    if _subscribers_gauge is not None:
        _subscribers_gauge.set(count)


# ---- router ----------------------------------------------------------------

router = APIRouter()


@router.get("/metrics")
def metrics_endpoint() -> Response:
    if not get_settings().metrics_enabled:
        return Response(
            content="metrics disabled",
            status_code=501,
            media_type="text/plain",
        )
    if not _PROMETHEUS_AVAILABLE or generate_latest is None:
        return Response(
            content="prometheus-client not installed",
            status_code=501,
            media_type="text/plain",
        )
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def _safe_capture_stats() -> list[dict[str, Any]]:
    """Pull stats() from every attached capture service, tolerating partial setups."""
    try:
        from backend.app.store import store as _store
    except Exception:  # noqa: BLE001
        return []

    out: list[dict[str, Any]] = []
    services_getter = getattr(_store, "all_capture_services", None)
    if services_getter is None:
        return out
    try:
        services = services_getter()
    except Exception:  # noqa: BLE001
        return out
    for service in services or []:
        try:
            stats_fn = getattr(service, "stats", None)
            if callable(stats_fn):
                out.append(stats_fn())
            else:
                out.append(
                    {
                        "session_name": getattr(service, "_session_name", None),
                        "target_pid": getattr(getattr(service, "target", None), "pid", None),
                    }
                )
        except Exception:  # noqa: BLE001
            continue
    return out


def _events_buffered_count() -> int:
    try:
        from backend.app.store import store as _store
    except Exception:  # noqa: BLE001
        return 0
    events = getattr(_store, "_events", None)
    if not events:
        return 0
    total = 0
    try:
        for deque_obj in events.values():
            try:
                total += len(deque_obj)
            except TypeError:
                continue
    except Exception:  # noqa: BLE001
        return total
    return total


def _subscriber_count() -> int:
    try:
        from backend.app.store import hub as _hub
    except Exception:  # noqa: BLE001
        return 0
    subs = getattr(_hub, "_subscribers", None)
    if not subs:
        return 0
    # Snapshot the values to avoid "dict changed size during iteration"
    # when subscribe/unsubscribe runs concurrently with /metrics or /api/health.
    try:
        snapshot = list(subs.values())
    except Exception:  # noqa: BLE001
        return 0
    total = 0
    for queues in snapshot:
        try:
            total += len(queues)
        except TypeError:
            continue
    return total


def _is_admin_safe() -> bool:
    try:
        from service.capture_service import is_admin

        return bool(is_admin())
    except Exception:  # noqa: BLE001
        return False


def _sessions_summary() -> tuple[int, int]:
    """(sessions_live, sessions_total)."""
    try:
        from backend.app.store import store as _store
    except Exception:  # noqa: BLE001
        return 0, 0
    total = 0
    live = 0
    try:
        sessions = _store.list()
        total = len(sessions)
        for session in sessions:
            status = (session.get("status") or "").lower()
            capture = (session.get("capture") or "").lower()
            if capture == "live" or status == "tracking":
                live += 1
    except Exception:  # noqa: BLE001
        pass
    return live, total


@router.get("/api/health")
def health_endpoint() -> JSONResponse:
    captures = _safe_capture_stats()
    subscribers = _subscriber_count()
    sessions_live, sessions_total = _sessions_summary()

    # Refresh gauges opportunistically — /api/health is cheap and frequently scraped.
    try:
        update_capture_gauges(captures)
        _set_subscribers_gauge(subscribers)
    except Exception:  # noqa: BLE001
        pass

    payload: dict[str, Any] = {
        "status": "ok",
        "admin": _is_admin_safe(),
        "uptime_seconds": round(time.monotonic() - _started_at, 3),
        "sessions_live": sessions_live,
        "sessions_total": sessions_total,
        "events_buffered": _events_buffered_count(),
        "subscribers": subscribers,
        "captures": captures,
        "log_dir": str(_resolve_log_dir()),
    }
    return JSONResponse(payload)
