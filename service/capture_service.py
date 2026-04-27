"""Real-time ETW-based activity capture for a target Windows process tree.

Subscribes to the four manifest-based kernel providers that together give
Procmon-class visibility:

  - Microsoft-Windows-Kernel-File      (open / read / write / delete / rename)
  - Microsoft-Windows-Kernel-Registry  (key + value create / set / delete)
  - Microsoft-Windows-Kernel-Process   (process / image / job)
  - Microsoft-Windows-Kernel-Network   (TCP + UDP send / recv / connect)

All events are filtered to the target PID and any descendant it spawns
(descendant set is pre-seeded from psutil at start, then maintained live
from the kernel ProcessStart events). NT device paths are rewritten to
DOS letters so the UI shows ``C:\\...`` instead of
``\\Device\\HarddiskVolume3\\...``.

Requires Administrator: kernel ETW providers cannot be enabled from a
limited token.
"""

from __future__ import annotations

import ctypes
import logging
import socket
import struct
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import psutil
from etw import ETW, GUID, ProviderInfo

from service.etw_cleanup import sweep_orphan_sessions

logger = logging.getLogger(__name__)


PROVIDER_FILE = GUID("{EDD08927-9CC4-4E65-B970-C2560FB5C289}")
PROVIDER_REGISTRY = GUID("{70EB4F03-C1DE-4F73-A051-33D13D5413BD}")
PROVIDER_PROCESS = GUID("{22FB2CD6-0E7B-422B-A0C7-2FAD1FD0E716}")
PROVIDER_NETWORK = GUID("{7DD42A49-5329-4832-8DFD-43D979153A88}")

PROVIDER_KIND: dict[str, str] = {
    str(PROVIDER_FILE).lower(): "file",
    str(PROVIDER_REGISTRY).lower(): "registry",
    str(PROVIDER_PROCESS).lower(): "process",
    str(PROVIDER_NETWORK).lower(): "network",
}


# Kernel-File keyword bits — enable everything that gives operation-level visibility.
FILE_KEYWORDS = (
    0x10    # FILEIO
    | 0x20  # OP_END
    | 0x80  # CREATE
    | 0x100  # READ
    | 0x200  # WRITE
    | 0x400  # DELETE_PATH
    | 0x800  # RENAME_SETLINK_PATH
    | 0x1000  # CREATE_NEW_FILE
)

# Kernel-Process: process lifecycle + image load + job membership.
PROCESS_KEYWORDS = 0x10 | 0x40 | 0x400

FILE_EVENTS: dict[int, str] = {
    12: "create",
    14: "close",
    15: "read",
    16: "write",
    17: "write",
    21: "set_information",
    22: "set_delete",
    23: "rename",
    24: "directory_enum",
    25: "directory_notify",
    26: "delete",
    27: "rename",
    28: "set_security",
    29: "query_security",
    30: "set_link",
}

REGISTRY_EVENTS: dict[int, str] = {
    1: "create_key",
    2: "open_key",
    3: "delete_key",
    4: "query_key",
    5: "set_value",
    6: "delete_value",
    7: "query_value",
    8: "enumerate_key",
    9: "enumerate_value",
    10: "kcb_create",
    11: "kcb_delete",
    12: "kcb_rundown_begin",
    13: "kcb_rundown_end",
    14: "set_information",
    15: "flush",
    16: "kcb_dirty",
    22: "close_key",
}

PROCESS_EVENTS: dict[int, str] = {
    1: "start",
    2: "stop",
    3: "thread_start",
    4: "thread_stop",
    5: "image_load",
    6: "image_unload",
}

NETWORK_EVENTS: dict[int, str] = {
    10: "tcp_send_v4",
    11: "tcp_recv_v4",
    12: "tcp_connect_v4",
    13: "tcp_disconnect_v4",
    14: "tcp_retransmit_v4",
    15: "tcp_accept_v4",
    16: "tcp_reconnect_v4",
    17: "tcp_fail",
    26: "udp_send_v4",
    27: "udp_recv_v4",
    28: "udp_fail",
    42: "tcp_send_v6",
    43: "tcp_recv_v6",
    44: "tcp_connect_v6",
    45: "tcp_disconnect_v6",
    46: "tcp_retransmit_v6",
    47: "tcp_accept_v6",
    48: "tcp_reconnect_v6",
    58: "udp_send_v6",
    59: "udp_recv_v6",
}


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def _build_dos_device_map() -> list[tuple[str, str]]:
    """Return (nt_prefix_lower, dos_letter) pairs sorted longest-first."""
    kernel32 = ctypes.windll.kernel32
    kernel32.QueryDosDeviceW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_ulong]
    kernel32.QueryDosDeviceW.restype = ctypes.c_ulong

    mapping: list[tuple[str, str]] = []
    buf = ctypes.create_unicode_buffer(1024)
    for letter_ord in range(ord("A"), ord("Z") + 1):
        letter = f"{chr(letter_ord)}:"
        if kernel32.QueryDosDeviceW(letter, buf, 1024):
            target = buf.value
            if target:
                mapping.append((target.lower(), letter))
    mapping.sort(key=lambda item: len(item[0]), reverse=True)
    return mapping


_UNC_PREFIXES: tuple[str, ...] = (
    r"\device\mup",
    r"\device\lanmanredirector",
)


def _translate_nt_path(path: str | None, dos_map: list[tuple[str, str]]) -> str | None:
    if not path:
        return path
    lowered = path.lower()
    # UNC: \Device\Mup\server\share\... -> \\server\share\...
    for unc_prefix in _UNC_PREFIXES:
        if lowered.startswith(unc_prefix):
            remainder = path[len(unc_prefix):]
            # remainder typically starts with "\"; collapse to a single leading "\"
            if remainder.startswith("\\"):
                return "\\" + remainder  # produces "\\server\share\..."
            return "\\\\" + remainder
    for nt_prefix, dos_letter in dos_map:
        if lowered.startswith(nt_prefix):
            return dos_letter + path[len(nt_prefix):]
    return path


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass
class CaptureTarget:
    exe_path: str
    pid: int
    pid_create_time: float | None = None


class CaptureService:
    """Streams ETW events for a target PID + descendants to a sync callback.

    The callback runs on the ETW consumer thread. Keep it cheap: hand the event
    off to a queue / asyncio loop; do not block.
    """

    def __init__(
        self,
        target: CaptureTarget,
        on_event: Callable[[dict[str, Any]], None],
    ) -> None:
        self.target = target
        self.on_event = on_event
        self._etw: ETW | None = None
        self._tracked_pids: set[int] = {target.pid}
        self._lock = threading.Lock()
        self._dos_map = _build_dos_device_map()
        # Lazy-import to avoid pulling pydantic into unrelated tests; the
        # backend always has it installed.
        try:
            from backend.app.config import get_settings

            self._file_object_cache_cap: int = int(get_settings().file_object_cache_size)
        except Exception:  # noqa: BLE001
            self._file_object_cache_cap = 100_000
        self._file_object_paths: OrderedDict[int, str] = OrderedDict()
        self._file_paths_lock = threading.Lock()
        self._pid_create_times: dict[int, float] = {}
        self._pid_create_lock = threading.Lock()
        self._session_name = f"ActivityTracker-{target.pid}-{int(time.time())}"
        self._stopped = False
        # Error sample-rate state.
        self._last_error_log: float = 0.0
        self._error_count: int = 0
        # Backpressure / observability.
        self._dropped_events: int = 0
        self._last_event_at: str | None = None

    # ---- lifecycle -------------------------------------------------------

    def start(self) -> None:
        if not is_admin():
            raise PermissionError(
                "ETW capture requires Administrator. Restart the backend in an elevated shell."
            )

        # Reap any ETW sessions left behind by a crashed prior run before we
        # try to create a brand-new one with the same prefix.
        try:
            stopped = sweep_orphan_sessions()
            if stopped:
                logger.info("swept %d orphan ETW session(s): %s", len(stopped), stopped)
        except Exception as exc:  # noqa: BLE001
            logger.warning("orphan ETW sweep failed: %s", exc)

        self._seed_descendants_from_psutil()

        providers = [
            ProviderInfo(
                "Microsoft-Windows-Kernel-File",
                PROVIDER_FILE,
                any_keywords=FILE_KEYWORDS,
            ),
            ProviderInfo(
                "Microsoft-Windows-Kernel-Registry",
                PROVIDER_REGISTRY,
            ),
            ProviderInfo(
                "Microsoft-Windows-Kernel-Process",
                PROVIDER_PROCESS,
                any_keywords=PROCESS_KEYWORDS,
            ),
            ProviderInfo(
                "Microsoft-Windows-Kernel-Network",
                PROVIDER_NETWORK,
            ),
        ]

        self._etw = ETW(
            session_name=self._session_name,
            providers=providers,
            event_callback=self._on_etw_event,
            ignore_exists_error=True,
        )
        self._etw.start()
        logger.info(
            "ETW capture started (session=%s, target_pid=%d, descendants=%d)",
            self._session_name,
            self.target.pid,
            len(self._tracked_pids),
        )

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        if self._etw is not None:
            try:
                self._etw.stop()
            except Exception as exc:  # noqa: BLE001
                logger.warning("ETW stop failed: %s", exc)
            self._etw = None
        logger.info("ETW capture stopped (session=%s)", self._session_name)

    # ---- helpers ---------------------------------------------------------

    def _seed_descendants_from_psutil(self) -> None:
        try:
            proc = psutil.Process(self.target.pid)
            with self._lock:
                for child in proc.children(recursive=True):
                    self._tracked_pids.add(child.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            logger.warning("could not enumerate children of pid %d: %s", self.target.pid, exc)

    def tracked_pids(self) -> set[int]:
        with self._lock:
            return set(self._tracked_pids)

    def _track_pid(self, pid: int) -> None:
        with self._lock:
            self._tracked_pids.add(pid)

    def _is_tracked(self, pid: int | None) -> bool:
        if pid is None:
            return False
        with self._lock:
            return pid in self._tracked_pids

    # ---- event pipeline --------------------------------------------------

    def _on_etw_event(self, event_tuple: tuple[int, dict[str, Any]]) -> None:
        try:
            event_id, data = event_tuple
            header = data.get("EventHeader") or {}
            provider_id = str(header.get("ProviderId", "")).lower()
            kind = PROVIDER_KIND.get(provider_id)
            if kind is None:
                return

            event_pid = _to_int(header.get("ProcessId"))

            if kind == "process":
                self._update_pid_set(event_id, data)
                # If the target itself stopped, drop its cached create_time so
                # a future PID with the same value isn't cross-validated against
                # stale data.
                if event_id == 2:  # ProcessStop
                    stop_pid = _to_int(data.get("ProcessID")) or _to_int(data.get("ProcessId"))
                    if stop_pid is not None:
                        with self._pid_create_lock:
                            self._pid_create_times.pop(stop_pid, None)

            # PID gate. Process events are also gated so we only emit
            # process-tree changes that involve the target tree.
            relevant_pid = event_pid
            if kind == "process":
                payload_pid = _to_int(data.get("ProcessID")) or _to_int(data.get("ProcessId"))
                if payload_pid is not None:
                    relevant_pid = payload_pid

            if not self._is_tracked(relevant_pid):
                return

            # PID-reuse protection: only relevant when the event is *for the
            # target itself*. Descendants are validated transitively via the
            # ProcessStart pid-set mutation.
            if (
                self.target.pid_create_time is not None
                and relevant_pid == self.target.pid
                and not self._verify_pid_identity(self.target.pid)
            ):
                return

            if kind == "file":
                self._track_file_object(event_id, data)

            normalized = self._normalize(event_id, data, kind, relevant_pid, header)
            if normalized is not None:
                self.on_event(normalized)
        except Exception as exc:  # noqa: BLE001
            self._error_count += 1
            now = time.monotonic()
            if now - self._last_error_log >= 5.0:
                self._last_error_log = now
                logger.warning("event handler error: %s", exc, exc_info=True)

    def _verify_pid_identity(self, pid: int) -> bool:
        """Return True iff the live process at ``pid`` matches our captured
        create_time within 1.0s. Unknown / inaccessible processes are accepted.
        """
        expected = self.target.pid_create_time
        if expected is None:
            return True
        with self._pid_create_lock:
            cached = self._pid_create_times.get(pid)
        if cached is None:
            try:
                cached = float(psutil.Process(pid).create_time())
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return True  # unknown — accept
            except Exception:  # noqa: BLE001
                return True
            with self._pid_create_lock:
                self._pid_create_times[pid] = cached
        return abs(cached - expected) <= 1.0

    def note_dropped(self, n: int = 1) -> None:
        """Record events dropped by a downstream queue (backpressure)."""
        self._dropped_events += n

    def stats(self) -> dict[str, Any]:
        return {
            "session_name": self._session_name,
            "target_pid": self.target.pid,
            "tracked_pids": len(self._tracked_pids),
            "file_object_cache_size": len(self._file_object_paths),
            "errors": self._error_count,
            "dropped": self._dropped_events,
            "last_event_at": self._last_event_at,
        }

    def _update_pid_set(self, event_id: int, data: dict[str, Any]) -> None:
        if event_id != 1:  # ProcessStart
            return
        new_pid = _to_int(data.get("ProcessID")) or _to_int(data.get("ProcessId"))
        parent_pid = _to_int(data.get("ParentProcessID")) or _to_int(data.get("ParentProcessId"))
        if new_pid is None or parent_pid is None:
            return
        with self._lock:
            if parent_pid in self._tracked_pids:
                self._tracked_pids.add(new_pid)

    def _track_file_object(self, event_id: int, data: dict[str, Any]) -> None:
        """Maintain a bounded FileObject -> path LRU so Read/Write events resolve to filenames."""
        file_object = _to_int(data.get("FileObject") or data.get("FileKey"))
        file_name = data.get("FileName") or data.get("OpenPath") or data.get("FilePath")

        # Create / Open: cache the mapping.
        if event_id == 12 and file_object is not None and isinstance(file_name, str) and file_name:
            translated = _translate_nt_path(file_name, self._dos_map)
            with self._file_paths_lock:
                cache = self._file_object_paths
                cache[file_object] = translated or file_name
                cache.move_to_end(file_object)
                cap = max(1, int(self._file_object_cache_cap))
                while len(cache) > cap:
                    cache.popitem(last=False)

        # Close: drop it.
        if event_id == 14 and file_object is not None:
            with self._file_paths_lock:
                self._file_object_paths.pop(file_object, None)

    def _resolve_file_path(self, data: dict[str, Any]) -> str | None:
        raw = data.get("FileName") or data.get("OpenPath") or data.get("FilePath")
        if isinstance(raw, str) and raw:
            return _translate_nt_path(raw, self._dos_map)

        file_object = _to_int(data.get("FileObject") or data.get("FileKey"))
        if file_object is None:
            return None
        with self._file_paths_lock:
            cached = self._file_object_paths.get(file_object)
            if cached is not None:
                self._file_object_paths.move_to_end(file_object)
            return cached

    # ---- normalization ---------------------------------------------------

    def _normalize(
        self,
        event_id: int,
        data: dict[str, Any],
        kind: str,
        pid: int | None,
        header: dict[str, Any],
    ) -> dict[str, Any] | None:
        timestamp = self._format_timestamp(header.get("TimeStamp"))
        self._last_event_at = timestamp

        if kind == "file":
            return {
                "kind": "file",
                "operation": FILE_EVENTS.get(event_id, f"event_{event_id}"),
                "pid": pid,
                "path": self._resolve_file_path(data),
                "timestamp": timestamp,
                "details": self._scrub_details(data, drop={"FileName", "OpenPath", "FilePath"}),
            }

        if kind == "registry":
            key_name = (
                data.get("KeyName")
                or data.get("RelativeName")
                or data.get("BaseName")
                or data.get("KeyHandle")
            )
            return {
                "kind": "registry",
                "operation": REGISTRY_EVENTS.get(event_id, f"event_{event_id}"),
                "pid": pid,
                "target": str(key_name) if key_name is not None else None,
                "timestamp": timestamp,
                "details": self._scrub_details(data),
            }

        if kind == "process":
            ppid = _to_int(data.get("ParentProcessID") or data.get("ParentProcessId"))
            image = data.get("ImageName") or data.get("ImageFileName")
            return {
                "kind": "process",
                "operation": PROCESS_EVENTS.get(event_id, f"event_{event_id}"),
                "pid": pid,
                "ppid": ppid,
                "path": _translate_nt_path(image, self._dos_map) if isinstance(image, str) else image,
                "timestamp": timestamp,
                "details": self._scrub_details(data),
            }

        if kind == "network":
            saddr = self._format_addr(data.get("saddr") or data.get("SourceAddress"))
            daddr = self._format_addr(data.get("daddr") or data.get("DestinationAddress"))
            sport = data.get("sport") or data.get("SourcePort")
            dport = data.get("dport") or data.get("DestinationPort")
            target: str | None = None
            if daddr and dport:
                target = f"{daddr}:{dport}"
            elif daddr:
                target = daddr
            return {
                "kind": "network",
                "operation": NETWORK_EVENTS.get(event_id, f"event_{event_id}"),
                "pid": pid,
                "target": target,
                "timestamp": timestamp,
                "details": {
                    "src": f"{saddr}:{sport}" if saddr and sport else saddr,
                    "size": data.get("size") or data.get("Size"),
                    **self._scrub_details(data, drop={
                        "saddr", "daddr", "sport", "dport",
                        "SourceAddress", "DestinationAddress",
                        "SourcePort", "DestinationPort",
                        "size", "Size",
                    }),
                },
            }

        return None

    @staticmethod
    def _scrub_details(data: dict[str, Any], drop: set[str] | None = None) -> dict[str, Any]:
        skip = {"EventHeader", "Task Name", "Description", "EventExtendedData", "UserData"}
        if drop:
            skip |= drop
        out: dict[str, Any] = {}
        for key, value in data.items():
            if key in skip:
                continue
            if isinstance(value, (bytes, bytearray)):
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                out[key] = value
            else:
                out[key] = str(value)
        return out

    @staticmethod
    def _format_timestamp(ts_raw: Any) -> str:
        if isinstance(ts_raw, int) and ts_raw > 0:
            seconds = (ts_raw - 116444736000000000) / 10_000_000
            try:
                return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
            except (OSError, OverflowError, ValueError):
                pass
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _format_addr(value: Any) -> str | None:
        if value is None or value == "":
            return None
        if isinstance(value, str):
            return value
        if isinstance(value, int):
            try:
                return socket.inet_ntoa(struct.pack("<I", value & 0xFFFFFFFF))
            except struct.error:
                return str(value)
        if isinstance(value, (bytes, bytearray)):
            if len(value) == 4:
                return socket.inet_ntoa(bytes(value))
            if len(value) == 16:
                return socket.inet_ntop(socket.AF_INET6, bytes(value))
        return str(value)
