"""Activity Tracker — GUI launcher.

Single-window Tk app that replaces start.bat / stop.bat in the release zip.

Responsibilities:
- self-elevate via UAC (re-launch as admin if not already)
- locate Python (PATH or known install locations)
- on first run: install runtime deps (pip install -r requirements.txt) and the
  optional MCP package (pip install -e ./mcp)
- spawn / supervise the FastAPI backend (uvicorn) as a subprocess
- live-stream backend stdout/stderr into a tabbed log viewer with ANSI colors,
  search, auto-scroll, save / clear, keyboard shortcuts
- Start / Stop / Restart with proper cleanup of orphan tracker_capture.exe and
  ETW sessions (logman -ets)

PyInstaller-bundled into a single tracker.exe for the release zip.
"""

from __future__ import annotations

import ctypes
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.request
import webbrowser
from collections import deque
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

APP_TITLE = "Activity Tracker"
DEFAULT_PORT = 8000
HEALTH_PATH = "/api/health"
METRICS_PATH = "/metrics"

KIND_COLORS = {
    "file": "#79c0ff",
    "registry": "#d2a8ff",
    "process": "#7ee787",
    "network": "#f1e05a",
    "custom": "#ff7b72",
    "other": "#8b949e",
}


# ---------- runtime / path resolution ---------------------------------------


def app_root() -> Path:
    """Folder the launcher considers 'home'.

    When frozen by PyInstaller, sys.executable is tracker.exe inside the
    release folder. When running as .py, it's the launcher folder, but for
    dev convenience we walk up to the repo root.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> None:
    """Re-spawn this exe with the 'runas' verb so Windows shows a UAC prompt."""
    params = " ".join(f'"{a}"' for a in sys.argv[1:])
    rc = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, params, None, 1
    )
    # ShellExecuteW returns >32 on success
    if rc <= 32:
        messagebox.showerror(
            APP_TITLE,
            "Could not request Administrator elevation. Right-click "
            "tracker.exe and choose 'Run as administrator'.",
        )
    sys.exit(0)


def find_python(root: Path | None = None) -> str | None:
    """Return a python.exe usable to run uvicorn, or None.

    Preference order:
    1. ``<release_root>/python/python.exe`` (embeddable Python that release.yml
       bundles into the zip — first-run is then offline-capable, and the user
       does not need to install Python at all).
    2. ``python`` on PATH.
    3. ``py -3`` on PATH.
    4. Known install locations under LOCALAPPDATA / Program Files.
    """
    if root is not None:
        bundled = root / "python" / "python.exe"
        if bundled.exists():
            return str(bundled)

    py = shutil.which("python")
    if py:
        return py
    py = shutil.which("py")
    if py:
        return py
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / f"Programs\\Python\\Python{v}\\python.exe"
        for v in ("313", "312", "311", "310")
    ] + [
        Path(os.environ.get("ProgramFiles", "")) / f"Python{v}\\python.exe"
        for v in ("313", "312", "311", "310")
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


# ---------- ANSI parser -----------------------------------------------------

# Minimal SGR (Select Graphic Rendition) parser. We only translate the colors
# uvicorn / fastapi actually emit; everything else is stripped.
_ANSI_RE = re.compile(r"\x1b\[([0-9;]*)m")

_SGR_TO_TAG = {
    "0": "reset",
    "1": "bold",
    "2": "dim",
    "30": "fg_black",
    "31": "fg_red",
    "32": "fg_green",
    "33": "fg_yellow",
    "34": "fg_blue",
    "35": "fg_magenta",
    "36": "fg_cyan",
    "37": "fg_white",
    "90": "fg_brblack",
    "91": "fg_brred",
    "92": "fg_brgreen",
    "93": "fg_bryellow",
    "94": "fg_brblue",
    "95": "fg_brmagenta",
    "96": "fg_brcyan",
    "97": "fg_brwhite",
}


def split_ansi(text: str) -> list[tuple[str, list[str]]]:
    """Split text into (chunk, active_tags) pairs."""
    out: list[tuple[str, list[str]]] = []
    active: list[str] = []
    pos = 0
    for m in _ANSI_RE.finditer(text):
        if m.start() > pos:
            out.append((text[pos : m.start()], list(active)))
        codes = m.group(1).split(";") if m.group(1) else ["0"]
        for c in codes:
            tag = _SGR_TO_TAG.get(c)
            if tag == "reset":
                active = []
            elif tag:
                # foreground codes overwrite previous foreground
                if tag.startswith("fg_"):
                    active = [t for t in active if not t.startswith("fg_")]
                active.append(tag)
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], list(active)))
    return out


# ---------- subprocess pump -------------------------------------------------


class BackendProcess:
    """Wraps a uvicorn subprocess and pumps its stdout to a callback."""

    def __init__(self, on_line: Callable[[str], None]) -> None:
        self._on_line = on_line
        self._proc: subprocess.Popen[bytes] | None = None
        self._threads: list[threading.Thread] = []

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc else None

    def start(self, python: str, root: Path, port: int) -> None:
        if self.running:
            return
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env.setdefault("PYTHONIOENCODING", "utf-8")
        # Ensure the release folder is on PYTHONPATH so `backend.app` and
        # `service.capture_service` resolve when uvicorn imports them.
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(root) + (os.pathsep + existing if existing else "")

        cmd = [
            python,
            "-u",
            "-m",
            "uvicorn",
            "backend.app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--ws-ping-interval",
            "60",
            "--ws-ping-timeout",
            "60",
        ]
        # CREATE_NO_WINDOW = 0x08000000 — keep the child fully hidden so the
        # only window the user sees is the launcher.
        creationflags = 0x08000000
        self._proc = subprocess.Popen(
            cmd,
            cwd=str(root),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            bufsize=0,
        )
        t = threading.Thread(target=self._pump, daemon=True)
        t.start()
        self._threads.append(t)

    def _pump(self) -> None:
        assert self._proc is not None
        assert self._proc.stdout is not None
        for raw in self._proc.stdout:
            try:
                line = raw.decode("utf-8", errors="replace")
            except Exception:
                line = repr(raw)
            self._on_line(line)
        self._on_line("\n[backend exited with code %s]\n" % self._proc.returncode)

    def stop(self, timeout: float = 5.0) -> None:
        if not self.running:
            return
        assert self._proc is not None
        try:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=timeout)
        except Exception:
            pass


# ---------- log file tail ---------------------------------------------------


class LogTail:
    """Background tail of a rotating log file. Push appends to a queue."""

    def __init__(self, path: Path, on_line: Callable[[str], None]) -> None:
        self._path = path
        self._on_line = on_line
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        pos = 0
        last_inode: tuple[int, int] | None = None
        while not self._stop.is_set():
            try:
                if not self._path.exists():
                    time.sleep(0.5)
                    continue
                st = self._path.stat()
                inode = (st.st_ino if hasattr(st, "st_ino") else 0, st.st_size)
                if last_inode is not None and inode[1] < last_inode[1]:
                    pos = 0  # rotated / truncated
                last_inode = inode
                with self._path.open("rb") as f:
                    f.seek(pos)
                    chunk = f.read()
                    pos = f.tell()
                if chunk:
                    try:
                        text = chunk.decode("utf-8", errors="replace")
                    except Exception:
                        text = repr(chunk)
                    self._on_line(text)
            except Exception:
                pass
            time.sleep(0.4)


# ---------- log viewer widget -----------------------------------------------


class LogView(ttk.Frame):
    """Polished log viewer: ANSI-coloured Text widget with toolbar."""

    PALETTE = {
        "bg": "#0e1116",
        "bg_alt": "#161b22",
        "fg": "#d6deeb",
        "fg_muted": "#8b949e",
        "accent": "#58a6ff",
        "border": "#30363d",
        "search_hi": "#3a4d2c",
        "select": "#264f78",
        # ANSI palette (close to VS Code Dark+)
        "fg_black": "#3b4048",
        "fg_red": "#f48771",
        "fg_green": "#7ec699",
        "fg_yellow": "#dcdcaa",
        "fg_blue": "#569cd6",
        "fg_magenta": "#c586c0",
        "fg_cyan": "#4ec9b0",
        "fg_white": "#d4d4d4",
        "fg_brblack": "#6a737d",
        "fg_brred": "#ff7b72",
        "fg_brgreen": "#7ee787",
        "fg_bryellow": "#f1e05a",
        "fg_brblue": "#79c0ff",
        "fg_brmagenta": "#d2a8ff",
        "fg_brcyan": "#a5d6ff",
        "fg_brwhite": "#f0f6fc",
    }

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent)
        self._auto_scroll = tk.BooleanVar(value=True)
        self._wrap = tk.BooleanVar(value=False)
        self._search_var = tk.StringVar()

        self._build_toolbar()
        self._build_text()

        # Pending lines, drained on the Tk main thread.
        self._pending: queue.Queue[str] = queue.Queue()
        self.after(80, self._drain)

    # ---- layout ------------------------------------------------------------

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self, style="Toolbar.TFrame")
        bar.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(bar, text="Search:", style="Muted.TLabel").pack(
            side=tk.LEFT, padx=(8, 4), pady=4
        )
        entry = ttk.Entry(bar, textvariable=self._search_var, width=28)
        entry.pack(side=tk.LEFT, pady=4)
        entry.bind("<KeyRelease>", lambda _e: self._highlight_search())
        entry.bind("<Return>", lambda _e: self._jump_to_next_match())

        ttk.Button(bar, text="×", width=2, command=self._clear_search).pack(
            side=tk.LEFT, padx=(2, 8)
        )

        ttk.Checkbutton(
            bar, text="Auto-scroll", variable=self._auto_scroll
        ).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(
            bar, text="Wrap", variable=self._wrap, command=self._toggle_wrap
        ).pack(side=tk.LEFT, padx=4)

        ttk.Button(bar, text="Clear", command=self.clear).pack(
            side=tk.RIGHT, padx=(4, 8), pady=4
        )
        ttk.Button(bar, text="Save…", command=self._save_dialog).pack(
            side=tk.RIGHT, padx=4, pady=4
        )
        ttk.Button(bar, text="Copy all", command=self._copy_all).pack(
            side=tk.RIGHT, padx=4, pady=4
        )

    def _build_text(self) -> None:
        wrap = ttk.Frame(self)
        wrap.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self._text = tk.Text(
            wrap,
            wrap="none",
            undo=False,
            background=self.PALETTE["bg"],
            foreground=self.PALETTE["fg"],
            insertbackground=self.PALETTE["fg"],
            selectbackground=self.PALETTE["select"],
            selectforeground=self.PALETTE["fg_brwhite"],
            font=("Cascadia Mono", 10),
            borderwidth=0,
            highlightthickness=0,
            padx=8,
            pady=4,
        )
        try:
            self._text.configure(font=("Cascadia Mono", 10))
        except tk.TclError:
            self._text.configure(font=("Consolas", 10))

        ysb = ttk.Scrollbar(wrap, orient=tk.VERTICAL, command=self._text.yview)
        xsb = ttk.Scrollbar(wrap, orient=tk.HORIZONTAL, command=self._text.xview)
        self._text.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)

        self._text.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)

        # Configure tags for ANSI colors and special markers.
        for code, color_key in (
            ("bold", None),
            ("dim", None),
            ("fg_black", "fg_black"),
            ("fg_red", "fg_red"),
            ("fg_green", "fg_green"),
            ("fg_yellow", "fg_yellow"),
            ("fg_blue", "fg_blue"),
            ("fg_magenta", "fg_magenta"),
            ("fg_cyan", "fg_cyan"),
            ("fg_white", "fg_white"),
            ("fg_brblack", "fg_brblack"),
            ("fg_brred", "fg_brred"),
            ("fg_brgreen", "fg_brgreen"),
            ("fg_bryellow", "fg_bryellow"),
            ("fg_brblue", "fg_brblue"),
            ("fg_brmagenta", "fg_brmagenta"),
            ("fg_brcyan", "fg_brcyan"),
            ("fg_brwhite", "fg_brwhite"),
        ):
            cfg: dict[str, str] = {}
            if code == "bold":
                cfg["font"] = ("Cascadia Mono", 10, "bold")
            elif code == "dim":
                cfg["foreground"] = self.PALETTE["fg_muted"]
            elif color_key:
                cfg["foreground"] = self.PALETTE[color_key]
            self._text.tag_configure(code, **cfg)

        self._text.tag_configure(
            "search",
            background=self.PALETTE["search_hi"],
            foreground=self.PALETTE["fg_brwhite"],
        )

        self._text.configure(state=tk.DISABLED)

        self._text.bind("<Control-f>", lambda _e: self._focus_search())
        self._text.bind("<Control-l>", lambda _e: self.clear())
        self._text.bind("<Control-s>", lambda _e: self._save_dialog())
        self._text.bind("<Control-a>", lambda _e: self._select_all())
        self._text.bind("<Button-3>", self._show_context_menu)

        self._build_context_menu()

    def _build_context_menu(self) -> None:
        m = tk.Menu(self, tearoff=False)
        m.add_command(label="Copy", command=self._copy_selection)
        m.add_command(label="Copy all", command=self._copy_all)
        m.add_separator()
        m.add_command(label="Select all", command=self._select_all)
        m.add_separator()
        m.add_command(label="Clear", command=self.clear)
        m.add_command(label="Save…", command=self._save_dialog)
        self._ctx_menu = m

    def _show_context_menu(self, event: tk.Event) -> None:
        try:
            self._ctx_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._ctx_menu.grab_release()

    # ---- public API --------------------------------------------------------

    def append(self, text: str) -> None:
        """Thread-safe: queue text for the next UI tick."""
        self._pending.put(text)

    def clear(self) -> None:
        self._text.configure(state=tk.NORMAL)
        self._text.delete("1.0", tk.END)
        self._text.configure(state=tk.DISABLED)

    # ---- internals ---------------------------------------------------------

    def _drain(self) -> None:
        try:
            chunks: list[str] = []
            while True:
                try:
                    chunks.append(self._pending.get_nowait())
                except queue.Empty:
                    break
            if chunks:
                self._render("".join(chunks))
        finally:
            self.after(80, self._drain)

    def _render(self, text: str) -> None:
        self._text.configure(state=tk.NORMAL)
        for chunk, tags in split_ansi(text):
            if not chunk:
                continue
            self._text.insert(tk.END, chunk, tuple(tags) if tags else None)
        self._text.configure(state=tk.DISABLED)
        if self._auto_scroll.get():
            self._text.see(tk.END)
        if self._search_var.get():
            self._highlight_search()

    def _toggle_wrap(self) -> None:
        self._text.configure(wrap="word" if self._wrap.get() else "none")

    def _focus_search(self) -> None:
        for w in self.winfo_children():
            for c in w.winfo_children():
                if isinstance(c, ttk.Entry):
                    c.focus_set()
                    return

    def _clear_search(self) -> None:
        self._search_var.set("")
        self._text.tag_remove("search", "1.0", tk.END)

    def _highlight_search(self) -> None:
        self._text.tag_remove("search", "1.0", tk.END)
        needle = self._search_var.get()
        if not needle:
            return
        idx = "1.0"
        while True:
            idx = self._text.search(needle, idx, nocase=True, stopindex=tk.END)
            if not idx:
                break
            end = f"{idx}+{len(needle)}c"
            self._text.tag_add("search", idx, end)
            idx = end

    def _jump_to_next_match(self) -> None:
        ranges = self._text.tag_ranges("search")
        if not ranges:
            return
        cursor = self._text.index(tk.INSERT)
        for i in range(0, len(ranges), 2):
            if str(ranges[i]) > cursor:
                self._text.mark_set(tk.INSERT, ranges[i])
                self._text.see(ranges[i])
                return
        # wrap to first
        self._text.mark_set(tk.INSERT, ranges[0])
        self._text.see(ranges[0])

    def _select_all(self) -> str:
        self._text.tag_add(tk.SEL, "1.0", tk.END)
        self._text.mark_set(tk.INSERT, "1.0")
        self._text.see(tk.INSERT)
        return "break"

    def _copy_selection(self) -> None:
        try:
            sel = self._text.get(tk.SEL_FIRST, tk.SEL_LAST)
        except tk.TclError:
            return
        self.clipboard_clear()
        self.clipboard_append(sel)

    def _copy_all(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self._text.get("1.0", "end-1c"))

    def _save_dialog(self) -> None:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = filedialog.asksaveasfilename(
            title="Save logs",
            defaultextension=".log",
            initialfile=f"tracker-{ts}.log",
            filetypes=[("Log file", "*.log"), ("Text", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            Path(path).write_text(
                self._text.get("1.0", "end-1c"), encoding="utf-8"
            )
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"Save failed: {exc}")


# ---------- Capture monitor: poller, sparkline, KPI card --------------------


class CaptureMetricsPoller:
    """Background thread polling /api/health, /metrics, and psutil for the
    native binary. Every tick (1 s) calls ``on_update`` on the main thread."""

    def __init__(self, on_update: Callable[[dict], None], port: int) -> None:
        self._on_update = on_update
        self._port = port
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_total: int | None = None
        self._last_per_kind: dict[str, int] = {}
        self._last_t: float = 0.0
        self._psutil_proc = None  # cached psutil.Process
        self._native_pid: int | None = None

    def start(self) -> None:
        if self._thread:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                m = self._collect()
                self._on_update(m)
            except Exception:
                pass
            self._stop.wait(1.0)

    def _collect(self) -> dict:
        now = time.time()
        m: dict = {
            "ts": now,
            "native_running": False,
            "native_pid": None,
            "native_cpu": 0.0,
            "native_rss_mb": 0.0,
            "native_threads": 0,
            "native_handles": 0,
            "native_uptime_s": 0,
            "events_total": None,
            "events_per_sec": None,
            "tracked_pids": 0,
            "file_object_cache_size": 0,
            "errors": 0,
            "dropped": 0,
            "session_name": "",
            "last_event_at": None,
            "by_kind": {},
            "by_kind_per_sec": {},
        }

        # psutil — find tracker_capture.exe and sample its metrics.
        try:
            import psutil  # type: ignore
            proc = self._psutil_proc
            if proc is None or not proc.is_running():
                proc = None
                for p in psutil.process_iter(["name", "pid"]):
                    try:
                        if (p.info.get("name") or "").lower() == "tracker_capture.exe":
                            proc = psutil.Process(p.info["pid"])
                            # warm cpu_percent — first call returns 0.0
                            proc.cpu_percent(interval=None)
                            break
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                self._psutil_proc = proc
                self._native_pid = proc.pid if proc else None
            if proc is not None:
                m["native_running"] = True
                m["native_pid"] = proc.pid
                m["native_cpu"] = proc.cpu_percent(interval=None)
                mi = proc.memory_info()
                m["native_rss_mb"] = mi.rss / 1024 / 1024
                m["native_threads"] = proc.num_threads()
                try:
                    m["native_handles"] = proc.num_handles()
                except (psutil.AccessDenied, AttributeError):
                    pass
                m["native_uptime_s"] = int(now - proc.create_time())
        except ImportError:
            pass
        except Exception:
            self._psutil_proc = None

        # /api/health for capture stats
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{self._port}/api/health", timeout=0.8
            ) as resp:
                health = json.loads(resp.read().decode("utf-8"))
            for s in health.get("captures", []) or []:
                m["tracked_pids"] += int(s.get("tracked_pids") or 0)
                m["file_object_cache_size"] += int(s.get("file_object_cache_size") or 0)
                m["errors"] += int(s.get("errors") or 0)
                m["dropped"] += int(s.get("dropped") or 0)
                if not m["session_name"]:
                    m["session_name"] = s.get("session_name") or ""
                if not m["last_event_at"]:
                    m["last_event_at"] = s.get("last_event_at")
        except Exception:
            pass

        # /metrics — parse Prometheus text for tracker_events_total{kind="..."}.
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{self._port}/metrics", timeout=0.8
            ) as resp:
                text = resp.read().decode("utf-8")
            by_kind: dict[str, int] = {}
            for line in text.splitlines():
                if line.startswith("tracker_events_total{"):
                    mm = re.match(r'tracker_events_total\{[^}]*kind="([^"]+)"[^}]*\}\s+([\d.eE+-]+)', line)
                    if mm:
                        try:
                            by_kind[mm.group(1)] = int(float(mm.group(2)))
                        except ValueError:
                            pass
            total = sum(by_kind.values())
            m["by_kind"] = by_kind
            m["events_total"] = total
            if self._last_total is not None and self._last_t:
                dt = now - self._last_t
                if dt > 0:
                    m["events_per_sec"] = max(0.0, (total - self._last_total) / dt)
                    m["by_kind_per_sec"] = {
                        k: max(0.0, (v - self._last_per_kind.get(k, 0)) / dt)
                        for k, v in by_kind.items()
                    }
            self._last_total = total
            self._last_per_kind = dict(by_kind)
            self._last_t = now
        except Exception:
            pass

        return m


class Sparkline(tk.Canvas):
    """Lightweight Tk Canvas line/area sparkline. Push values, redraws on its own."""

    def __init__(
        self,
        parent: tk.Widget,
        *,
        height: int = 70,
        color: str = "#58a6ff",
        fill: bool = False,
        capacity: int = 60,
        max_value: float | None = None,
    ) -> None:
        super().__init__(
            parent,
            height=height,
            bg="#0e1116",
            highlightthickness=1,
            highlightbackground="#21262d",
        )
        self._color = color
        self._fill = fill
        self._values: deque[float] = deque(maxlen=capacity)
        self._capacity = capacity
        self._max_value = max_value
        self.bind("<Configure>", lambda _e: self._redraw())

    def push(self, value: float) -> None:
        try:
            self._values.append(float(value))
        except (TypeError, ValueError):
            return
        self._redraw()

    def reset(self) -> None:
        self._values.clear()
        self._redraw()

    def _redraw(self) -> None:
        self.delete("all")
        w = max(1, self.winfo_width())
        h = max(1, self.winfo_height())
        if not self._values:
            self.create_text(
                w - 6, 6, anchor="ne", text="—", fill="#8b949e", font=("Cascadia Mono", 9)
            )
            return
        max_v = self._max_value if self._max_value is not None else max(self._values)
        if max_v <= 0:
            max_v = 1.0
        n = self._capacity
        step = w / max(1, n - 1)
        offset = n - len(self._values)
        pts: list[float] = []
        for i, v in enumerate(self._values):
            x = (i + offset) * step
            y = h - (v / max_v) * (h - 6) - 3
            pts.extend([x, y])
        if self._fill and len(pts) >= 4:
            poly = list(pts) + [pts[-2], h, pts[0], h]
            try:
                self.create_polygon(poly, fill=self._color, outline="", stipple="gray25")
            except tk.TclError:
                pass
        if len(pts) >= 4:
            self.create_line(pts, fill=self._color, width=2)
        last = self._values[-1]
        self.create_text(
            w - 6,
            6,
            anchor="ne",
            text=f"{last:,.1f}",
            fill="#d6deeb",
            font=("Cascadia Mono", 9),
        )


class KpiCard(ttk.Frame):
    def __init__(self, parent: tk.Widget, label: str) -> None:
        super().__init__(parent, style="Card.TFrame", padding=(10, 8))
        self._lbl = ttk.Label(
            self, text=label.upper(), style="Card.TLabel", font=("Segoe UI", 8)
        )
        self._lbl.pack(anchor="w")
        self._val = ttk.Label(
            self,
            text="—",
            style="CardValue.TLabel",
            font=("Cascadia Mono", 18, "bold"),
        )
        self._val.pack(anchor="w", pady=(4, 0))

    def set_value(self, text: str, color: str | None = None) -> None:
        self._val.configure(text=text)
        if color:
            self._val.configure(foreground=color)


class CaptureMonitor(ttk.Frame):
    """Capture tab: status, KPIs, sparklines, per-kind bars, recent errors."""

    def __init__(
        self,
        parent: tk.Widget,
        *,
        on_open_native_log: Callable[[], None],
        on_restart_capture: Callable[[], None],
        on_kill_capture: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self._on_open_native_log = on_open_native_log
        self._on_restart_capture = on_restart_capture
        self._on_kill_capture = on_kill_capture
        self._build()

    def _build(self) -> None:
        # Top status bar
        top = ttk.Frame(self, style="Header.TFrame")
        top.pack(side=tk.TOP, fill=tk.X)

        self._status_dot = tk.Canvas(
            top, width=14, height=14, bg="#161b22", highlightthickness=0
        )
        self._status_circle = self._status_dot.create_oval(
            2, 2, 12, 12, fill="#6e7681", outline=""
        )
        self._status_dot.pack(side=tk.LEFT, padx=(12, 6), pady=10)

        self._status_lbl = ttk.Label(
            top, text="tracker_capture.exe — Stopped", style="Status.TLabel"
        )
        self._status_lbl.pack(side=tk.LEFT)

        ttk.Separator(top, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=8, pady=6
        )
        self._uptime_lbl = ttk.Label(top, text="Uptime —", style="Pill.TLabel")
        self._uptime_lbl.pack(side=tk.LEFT, padx=4, pady=8)

        ttk.Separator(top, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=8, pady=6
        )
        self._session_lbl = ttk.Label(top, text="Session —", style="Pill.TLabel")
        self._session_lbl.pack(side=tk.LEFT, padx=4, pady=8)

        ttk.Button(top, text="↻  Restart capture", command=self._on_restart_capture).pack(
            side=tk.RIGHT, padx=4, pady=8
        )
        ttk.Button(top, text="■  Kill", command=self._on_kill_capture).pack(
            side=tk.RIGHT, padx=4, pady=8
        )
        ttk.Button(top, text="📝  native.log", command=self._on_open_native_log).pack(
            side=tk.RIGHT, padx=4, pady=8
        )

        # KPI grid (8 cards in 2 rows)
        kpi_frame = ttk.Frame(self)
        kpi_frame.pack(fill=tk.X, padx=12, pady=(10, 6))
        names = [
            "events/sec",
            "total events",
            "tracked pids",
            "cache size",
            "cpu %",
            "ram (mb)",
            "threads",
            "handles",
        ]
        self._kpis: dict[str, KpiCard] = {}
        for i, name in enumerate(names):
            card = KpiCard(kpi_frame, name)
            card.grid(row=i // 4, column=i % 4, sticky="nsew", padx=4, pady=4)
            self._kpis[name] = card
        for i in range(4):
            kpi_frame.columnconfigure(i, weight=1)

        # Charts (3 sparklines stacked)
        charts = ttk.Frame(self)
        charts.pack(fill=tk.BOTH, expand=True, padx=12, pady=2)

        ttk.Label(charts, text="Events / sec  (60 s window)", style="Muted.TLabel").grid(
            row=0, column=0, sticky="w", padx=4, pady=(4, 0)
        )
        self._spark_events = Sparkline(charts, height=80, color="#79c0ff", fill=True)
        self._spark_events.grid(row=1, column=0, sticky="nsew", padx=4, pady=(2, 6))

        ttk.Label(charts, text="CPU  %", style="Muted.TLabel").grid(
            row=2, column=0, sticky="w", padx=4
        )
        self._spark_cpu = Sparkline(charts, height=60, color="#7ee787", max_value=100.0)
        self._spark_cpu.grid(row=3, column=0, sticky="nsew", padx=4, pady=(2, 6))

        ttk.Label(charts, text="RAM  MB", style="Muted.TLabel").grid(
            row=4, column=0, sticky="w", padx=4
        )
        self._spark_ram = Sparkline(charts, height=60, color="#d2a8ff")
        self._spark_ram.grid(row=5, column=0, sticky="nsew", padx=4, pady=(2, 6))

        charts.columnconfigure(0, weight=1)
        for r in (1, 3, 5):
            charts.rowconfigure(r, weight=1)

        # Per-kind bar chart
        bottom = ttk.Frame(self)
        bottom.pack(fill=tk.X, padx=12, pady=(0, 10))
        ttk.Label(
            bottom, text="Events by kind  (cumulative)", style="Muted.TLabel"
        ).pack(anchor="w", padx=4)
        self._kind_canvas = tk.Canvas(
            bottom,
            height=110,
            bg="#0e1116",
            highlightthickness=1,
            highlightbackground="#21262d",
        )
        self._kind_canvas.pack(fill=tk.X, padx=4, pady=(4, 0))
        self._kind_canvas.bind("<Configure>", lambda _e: self._redraw_kind_bars())
        self._last_by_kind: dict[str, int] = {}

    # ---- public update API -------------------------------------------------

    def update_metrics(self, m: dict) -> None:
        # Status pill
        if m["native_running"]:
            self._status_dot.itemconfigure(self._status_circle, fill="#3fb950")
            self._status_lbl.configure(
                text=f"tracker_capture.exe — Running (pid {m['native_pid']})"
            )
            up = m["native_uptime_s"]
            h, rem = divmod(up, 3600)
            mn, sec = divmod(rem, 60)
            self._uptime_lbl.configure(text=f"Uptime  {h:02}:{mn:02}:{sec:02}")
        else:
            self._status_dot.itemconfigure(self._status_circle, fill="#6e7681")
            self._status_lbl.configure(text="tracker_capture.exe — Stopped")
            self._uptime_lbl.configure(text="Uptime —")
        self._session_lbl.configure(
            text=f"Session  {m['session_name'] or '—'}"
        )

        eps = m.get("events_per_sec")
        self._kpis["events/sec"].set_value(
            f"{eps:,.0f}" if eps is not None else "—",
            "#7ee787" if eps and eps > 0 else "#f0f6fc",
        )
        tot = m.get("events_total")
        self._kpis["total events"].set_value(f"{tot:,}" if tot is not None else "—")
        self._kpis["tracked pids"].set_value(f"{m['tracked_pids']:,}")
        self._kpis["cache size"].set_value(f"{m['file_object_cache_size']:,}")
        self._kpis["cpu %"].set_value(f"{m['native_cpu']:.1f}%")
        self._kpis["ram (mb)"].set_value(f"{m['native_rss_mb']:.1f}")
        self._kpis["threads"].set_value(f"{m['native_threads']}")
        self._kpis["handles"].set_value(f"{m['native_handles']}")

        if eps is not None:
            self._spark_events.push(eps)
        self._spark_cpu.push(m["native_cpu"])
        self._spark_ram.push(m["native_rss_mb"])

        self._last_by_kind = m["by_kind"]
        self._redraw_kind_bars()

    def _redraw_kind_bars(self) -> None:
        c = self._kind_canvas
        c.delete("all")
        if not self._last_by_kind:
            c.create_text(
                12, 14, anchor="w", text="(no events)", fill="#8b949e",
                font=("Cascadia Mono", 9),
            )
            return
        w = max(1, c.winfo_width())
        h = max(1, c.winfo_height())
        kinds = sorted(self._last_by_kind.items(), key=lambda x: -x[1])
        max_v = max(v for _, v in kinds) or 1
        bar_h = (h - 8) / max(1, len(kinds))
        label_w = 90
        right_pad = 90
        for i, (kind, v) in enumerate(kinds):
            y = 4 + i * bar_h
            color = KIND_COLORS.get(kind.lower(), KIND_COLORS["other"])
            ratio = v / max_v
            bar_w = max(0.0, (w - label_w - right_pad) * ratio)
            c.create_text(
                10,
                y + bar_h / 2,
                anchor="w",
                text=kind,
                fill="#d6deeb",
                font=("Cascadia Mono", 10, "bold"),
            )
            c.create_rectangle(
                label_w, y + 3, label_w + bar_w, y + bar_h - 3, fill=color, outline=""
            )
            c.create_text(
                label_w + bar_w + 6,
                y + bar_h / 2,
                anchor="w",
                text=f"{v:,}",
                fill="#d6deeb",
                font=("Cascadia Mono", 9),
            )


# ---------- main app --------------------------------------------------------


class TrackerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root_path = app_root()
        self.python = find_python(self.root_path)
        self.port = int(os.environ.get("TRACKER_PORT", str(DEFAULT_PORT)))
        self._setup_done = False
        self._log_tails: list[LogTail] = []
        self._poller: CaptureMetricsPoller | None = None

        self._configure_root()
        self._build_layout()

        self.backend = BackendProcess(on_line=self._on_backend_line)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._set_status("stopped")
        self._refresh_admin_badge()
        self._log_info("ready. click Start to launch the backend.")

        # Bind global shortcuts.
        self.root.bind("<F5>", lambda _e: self._on_restart())
        self.root.bind("<Control-q>", lambda _e: self._on_close())

    # ---- styling ----------------------------------------------------------

    def _configure_root(self) -> None:
        self.root.title(APP_TITLE)
        self.root.geometry("1100x700")
        self.root.minsize(720, 460)

        try:
            ico = self.root_path / "service" / "native" / "resources" / "tracker.ico"
            if ico.exists():
                self.root.iconbitmap(default=str(ico))
        except Exception:
            pass

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        bg = "#0e1116"
        bg_alt = "#161b22"
        fg = "#d6deeb"
        muted = "#8b949e"
        border = "#30363d"
        accent = "#58a6ff"

        self.root.configure(background=bg)

        style.configure(".", background=bg, foreground=fg, fieldbackground=bg_alt)
        style.configure("TFrame", background=bg)
        style.configure("Toolbar.TFrame", background=bg_alt)
        style.configure("Header.TFrame", background=bg_alt)
        style.configure("TLabel", background=bg, foreground=fg)
        style.configure("Header.TLabel", background=bg_alt, foreground=fg)
        style.configure("Muted.TLabel", background=bg_alt, foreground=muted)
        style.configure("Status.TLabel", background=bg_alt, foreground=fg, padding=(8, 4))
        style.configure("Pill.TLabel", background=bg_alt, foreground=fg, padding=(8, 2))
        style.configure(
            "TButton",
            background=bg_alt,
            foreground=fg,
            borderwidth=1,
            focusthickness=0,
            padding=(10, 4),
        )
        style.map(
            "TButton",
            background=[("active", border), ("disabled", bg_alt)],
            foreground=[("disabled", muted)],
        )
        style.configure(
            "Accent.TButton", background=accent, foreground="#0d1117", padding=(14, 6)
        )
        style.map("Accent.TButton", background=[("active", "#79c0ff")])
        style.configure("TCheckbutton", background=bg_alt, foreground=fg)
        style.map("TCheckbutton", background=[("active", bg_alt)])
        style.configure("TEntry", fieldbackground=bg_alt, foreground=fg, insertcolor=fg)
        style.configure("TCombobox", fieldbackground=bg_alt, foreground=fg)
        style.configure("TNotebook", background=bg, borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background=bg,
            foreground=muted,
            padding=(14, 6),
            borderwidth=0,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", bg_alt)],
            foreground=[("selected", fg)],
        )
        style.configure("TSeparator", background=border)
        style.configure("Card.TFrame", background=bg_alt, relief="flat")
        style.configure("Card.TLabel", background=bg_alt, foreground=muted)
        style.configure("CardValue.TLabel", background=bg_alt, foreground="#f0f6fc")

    # ---- layout -----------------------------------------------------------

    def _build_layout(self) -> None:
        # ----- top header (status + admin + port) ------------------------
        header = ttk.Frame(self.root, style="Header.TFrame")
        header.pack(side=tk.TOP, fill=tk.X)

        self.status_dot = tk.Canvas(
            header, width=14, height=14, bg="#161b22", highlightthickness=0
        )
        self._status_circle = self.status_dot.create_oval(
            2, 2, 12, 12, fill="#6e7681", outline=""
        )
        self.status_dot.pack(side=tk.LEFT, padx=(12, 6), pady=8)

        self.status_label = ttk.Label(header, text="Stopped", style="Status.TLabel")
        self.status_label.pack(side=tk.LEFT)

        ttk.Separator(header, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8, pady=6)

        self.admin_label = ttk.Label(header, text="Admin: ?", style="Pill.TLabel")
        self.admin_label.pack(side=tk.LEFT, padx=4, pady=8)

        ttk.Separator(header, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8, pady=6)

        self.port_label = ttk.Label(
            header, text=f"Port: {self.port}", style="Pill.TLabel"
        )
        self.port_label.pack(side=tk.LEFT, padx=4, pady=8)

        ttk.Label(header, text=APP_TITLE, style="Header.TLabel").pack(
            side=tk.RIGHT, padx=12
        )

        # ----- action row -------------------------------------------------
        actions = ttk.Frame(self.root, style="Toolbar.TFrame")
        actions.pack(side=tk.TOP, fill=tk.X)

        self.btn_start = ttk.Button(
            actions, text="▶  Start", style="Accent.TButton", command=self._on_start
        )
        self.btn_start.pack(side=tk.LEFT, padx=(8, 4), pady=8)

        self.btn_stop = ttk.Button(actions, text="■  Stop", command=self._on_stop)
        self.btn_stop.pack(side=tk.LEFT, padx=4, pady=8)

        self.btn_restart = ttk.Button(
            actions, text="↻  Restart", command=self._on_restart
        )
        self.btn_restart.pack(side=tk.LEFT, padx=4, pady=8)

        ttk.Separator(actions, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=8, pady=6
        )

        ttk.Button(
            actions, text="🌐  Open in browser", command=self._on_open_browser
        ).pack(side=tk.LEFT, padx=4, pady=8)
        ttk.Button(actions, text="📁  Open folder", command=self._on_open_folder).pack(
            side=tk.LEFT, padx=4, pady=8
        )
        ttk.Button(actions, text="ℹ  About", command=self._on_about).pack(
            side=tk.RIGHT, padx=8, pady=8
        )

        # ----- main tabs (capture monitor + per-stream log views) ---------
        self.tabs = ttk.Notebook(self.root)
        self.tabs.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.capture = CaptureMonitor(
            self.tabs,
            on_open_native_log=self._on_open_native_log,
            on_restart_capture=self._on_restart_capture,
            on_kill_capture=self._on_kill_capture,
        )
        self.log_backend = LogView(self.tabs)
        self.log_events = LogView(self.tabs)
        self.log_errors = LogView(self.tabs)
        self.log_native = LogView(self.tabs)

        self.tabs.add(self.capture, text="Capture")
        self.tabs.add(self.log_backend, text="Backend")
        self.tabs.add(self.log_events, text="Events")
        self.tabs.add(self.log_errors, text="Errors")
        self.tabs.add(self.log_native, text="Native")

        # ----- footer -----------------------------------------------------
        footer = ttk.Frame(self.root, style="Toolbar.TFrame")
        footer.pack(side=tk.BOTTOM, fill=tk.X)
        self.footer_label = ttk.Label(
            footer,
            text=f"Folder: {self.root_path}",
            style="Muted.TLabel",
            anchor="w",
        )
        self.footer_label.pack(side=tk.LEFT, padx=8, pady=4)
        ttk.Label(
            footer, text="F5 = restart   Ctrl+Q = quit", style="Muted.TLabel"
        ).pack(side=tk.RIGHT, padx=8, pady=4)

    # ---- status ----------------------------------------------------------

    def _set_status(self, state: str) -> None:
        colors = {
            "stopped": ("#6e7681", "Stopped"),
            "starting": ("#d29922", "Starting…"),
            "running": ("#3fb950", "Running"),
            "stopping": ("#d29922", "Stopping…"),
            "error": ("#f85149", "Error"),
        }
        color, label = colors.get(state, ("#6e7681", state.title()))
        self.status_dot.itemconfigure(self._status_circle, fill=color)
        self.status_label.configure(text=label)

    def _refresh_admin_badge(self) -> None:
        if is_admin():
            self.admin_label.configure(text="Admin: ✓", foreground="#7ee787")
        else:
            self.admin_label.configure(text="Admin: ✗", foreground="#f85149")

    # ---- log helpers -----------------------------------------------------

    def _log_info(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_backend.append(f"\x1b[2m{ts}\x1b[0m \x1b[36mlauncher\x1b[0m  {msg}\n")

    def _log_warn(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_backend.append(f"\x1b[2m{ts}\x1b[0m \x1b[33mlauncher\x1b[0m  {msg}\n")

    def _log_error(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_backend.append(f"\x1b[2m{ts}\x1b[0m \x1b[31mlauncher\x1b[0m  {msg}\n")

    def _on_backend_line(self, line: str) -> None:
        self.log_backend.append(line)

    # ---- one-time setup --------------------------------------------------

    def _ensure_setup(self) -> bool:
        if self._setup_done:
            return True
        if not self.python:
            self._log_error(
                "Python 3.10+ not found on PATH. Install it from https://www.python.org/downloads/"
            )
            messagebox.showerror(
                APP_TITLE,
                "Python 3.10+ is required.\n\n"
                "Install it from python.org and tick "
                '"Add Python to PATH" during install, then re-launch.',
            )
            return False

        # Verify the heavy artefacts that only the dev / CI build produces.
        bin1 = self.root_path / "service" / "native" / "build" / "tracker_capture.exe"
        bin2 = (
            self.root_path
            / "service"
            / "native"
            / "build"
            / "Release"
            / "tracker_capture.exe"
        )
        if not (bin1.exists() or bin2.exists()):
            self._log_error("tracker_capture.exe missing — release zip is incomplete.")
            messagebox.showerror(
                APP_TITLE,
                "tracker_capture.exe is missing. The release zip is incomplete; "
                "re-extract it preserving folder structure.",
            )
            return False

        ui_index = self.root_path / "ui" / "dist" / "index.html"
        if not ui_index.exists():
            self._log_error("ui/dist/index.html missing — release zip is incomplete.")
            messagebox.showerror(
                APP_TITLE,
                "ui/dist/index.html is missing. The release zip is incomplete; "
                "re-extract it preserving folder structure.",
            )
            return False

        # First-run: install runtime dependencies if they're not importable.
        ok = self._maybe_pip_install()
        if not ok:
            return False

        self._setup_done = True
        return True

    def _maybe_pip_install(self) -> bool:
        # Cheap import probe; uvicorn is heaviest so test that.
        probe = subprocess.run(
            [self.python, "-c", "import fastapi, psutil, pydantic_settings, prometheus_client"],
            capture_output=True,
            creationflags=0x08000000,
        )
        if probe.returncode == 0:
            return True

        self._log_info("first run — installing runtime dependencies (~30 MB)…")
        req = self.root_path / "requirements.txt"
        if not req.exists():
            self._log_error(f"requirements.txt not found at {req}")
            return False
        rc = self._run_blocking([self.python, "-m", "pip", "install", "--upgrade", "pip"])
        if rc != 0:
            self._log_error("pip upgrade failed.")
            return False
        rc = self._run_blocking([self.python, "-m", "pip", "install", "-r", str(req)])
        if rc != 0:
            self._log_error("pip install -r requirements.txt failed.")
            return False

        # Optional: install the bundled MCP server.
        mcp_pyproject = self.root_path / "mcp" / "pyproject.toml"
        if mcp_pyproject.exists():
            self._log_info("installing MCP server (optional)…")
            rc = self._run_blocking(
                [self.python, "-m", "pip", "install", "-e", str(self.root_path / "mcp")]
            )
            if rc != 0:
                self._log_warn("MCP install failed; backend will still run.")

        self._log_info("dependencies installed.")
        return True

    def _run_blocking(self, cmd: list[str]) -> int:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=0x08000000,
            cwd=str(self.root_path),
            bufsize=0,
        )
        assert proc.stdout is not None
        for raw in proc.stdout:
            try:
                self.log_backend.append(raw.decode("utf-8", errors="replace"))
            except Exception:
                self.log_backend.append(repr(raw) + "\n")
        return proc.wait()

    # ---- log file tails --------------------------------------------------

    def _start_log_tails(self) -> None:
        for t in self._log_tails:
            t.stop()
        self._log_tails.clear()
        log_dir = self.root_path / "logs"
        targets = [
            ("events.log", self.log_events),
            ("errors.log", self.log_errors),
            ("native.log", self.log_native),
        ]
        for name, view in targets:
            tail = LogTail(log_dir / name, view.append)
            tail.start()
            self._log_tails.append(tail)

    def _stop_log_tails(self) -> None:
        for t in self._log_tails:
            t.stop()
        self._log_tails.clear()

    # ---- button actions --------------------------------------------------

    def _on_start(self) -> None:
        if self.backend.running:
            self._log_warn("backend already running.")
            return
        if not self._ensure_setup():
            self._set_status("error")
            return
        self._set_status("starting")
        try:
            self.backend.start(self.python or "python", self.root_path, self.port)
        except Exception as exc:
            self._log_error(f"failed to start backend: {exc}")
            self._set_status("error")
            return
        self._start_log_tails()
        self._start_poller()
        self._log_info(f"backend pid={self.backend.pid} on http://127.0.0.1:{self.port}")
        # Poll /api/health for readiness, then mark Running.
        threading.Thread(target=self._wait_until_ready, daemon=True).start()

    def _wait_until_ready(self) -> None:
        import urllib.request

        url = f"http://127.0.0.1:{self.port}{HEALTH_PATH}"
        for _ in range(60):
            if not self.backend.running:
                self.root.after(0, lambda: self._set_status("error"))
                return
            try:
                with urllib.request.urlopen(url, timeout=1) as resp:
                    if resp.status == 200:
                        self.root.after(0, lambda: self._set_status("running"))
                        self.root.after(0, lambda: self._log_info("backend ready."))
                        return
            except Exception:
                pass
            time.sleep(0.5)
        self.root.after(0, lambda: self._set_status("error"))
        self.root.after(0, lambda: self._log_error("backend did not become ready."))

    def _on_stop(self) -> None:
        if not self.backend.running:
            self._cleanup_orphans()
            self._set_status("stopped")
            return
        self._set_status("stopping")
        threading.Thread(target=self._stop_worker, daemon=True).start()

    def _stop_worker(self) -> None:
        self._log_info("stopping backend…")
        self.backend.stop()
        self._cleanup_orphans()
        self._stop_log_tails()
        self._stop_poller()
        self.root.after(0, lambda: self._set_status("stopped"))
        self.root.after(0, lambda: self._log_info("backend stopped."))

    def _cleanup_orphans(self) -> None:
        # Mirror stop.bat: kill orphan tracker_capture.exe + any leftover
        # ActivityTracker-* ETW sessions via logman (universally available
        # on Windows 10 / 11; no PowerShell module dependency).
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", "tracker_capture.exe"],
                capture_output=True,
                creationflags=0x08000000,
                timeout=5,
            )
        except Exception:
            pass
        try:
            r = subprocess.run(
                ["logman", "query", "-ets"],
                capture_output=True,
                text=True,
                creationflags=0x08000000,
                timeout=5,
            )
            for line in (r.stdout or "").splitlines():
                line = line.strip()
                if line.startswith("ActivityTracker-"):
                    name = line.split()[0]
                    subprocess.run(
                        ["logman", "stop", name, "-ets"],
                        capture_output=True,
                        creationflags=0x08000000,
                        timeout=5,
                    )
        except Exception:
            pass

    def _on_restart(self) -> None:
        threading.Thread(target=self._restart_worker, daemon=True).start()

    def _restart_worker(self) -> None:
        if self.backend.running:
            self.root.after(0, lambda: self._set_status("stopping"))
            self.backend.stop()
            self._stop_log_tails()
            self._cleanup_orphans()
        self.root.after(0, self._on_start)

    # ---- capture-tab callbacks ----------------------------------------

    def _start_poller(self) -> None:
        if self._poller is not None:
            return
        self._poller = CaptureMetricsPoller(
            on_update=lambda m: self.root.after(0, lambda: self.capture.update_metrics(m)),
            port=self.port,
        )
        self._poller.start()

    def _stop_poller(self) -> None:
        if self._poller is not None:
            self._poller.stop()
            self._poller = None

    def _on_open_native_log(self) -> None:
        f = self.root_path / "logs" / "native.log"
        if not f.exists():
            messagebox.showinfo(
                APP_TITLE,
                f"native.log does not exist yet at\n{f}\n\nIt is created once "
                "the backend has spawned the native binary.",
            )
            return
        try:
            os.startfile(str(f))
        except Exception as exc:
            self._log_error(f"open native.log failed: {exc}")

    def _on_restart_capture(self) -> None:
        # Killing tracker_capture.exe makes the backend's CaptureService notice
        # the EOF on stdout and surface a 'failed' status; the user can then
        # re-create the session from the UI. We do NOT respawn here directly
        # because the spawn is owned by the active session, not the launcher.
        if not messagebox.askyesno(
            APP_TITLE,
            "Restart the native capture?\n\n"
            "tracker_capture.exe will be killed. The backend will notice and "
            "surface a 'failed' status; re-create the session from the web UI.",
        ):
            return
        threading.Thread(target=self._cleanup_orphans, daemon=True).start()
        self._log_info("restart capture: native binary killed.")

    def _on_kill_capture(self) -> None:
        if not messagebox.askyesno(
            APP_TITLE,
            "Force-kill tracker_capture.exe?\n\n"
            "The backend session will be marked 'failed'. The launcher and "
            "the FastAPI backend stay running.",
        ):
            return
        threading.Thread(target=self._cleanup_orphans, daemon=True).start()
        self._log_warn("force-kill capture: tracker_capture.exe terminated.")

    def _on_open_browser(self) -> None:
        webbrowser.open(f"http://127.0.0.1:{self.port}")

    def _on_open_folder(self) -> None:
        try:
            os.startfile(str(self.root_path))
        except Exception as exc:
            self._log_error(f"open folder failed: {exc}")

    def _on_about(self) -> None:
        messagebox.showinfo(
            APP_TITLE,
            f"{APP_TITLE}\n\n"
            f"Folder: {self.root_path}\n"
            f"Port:   {self.port}\n"
            f"Admin:  {'yes' if is_admin() else 'no'}\n"
            f"Python: {self.python or 'not found'}\n\n"
            "https://github.com/botnick/Program-Activity-Tracker",
        )

    def _on_close(self) -> None:
        if self.backend.running:
            ok = messagebox.askyesno(
                APP_TITLE, "Backend is running. Stop it and quit?"
            )
            if not ok:
                return
        try:
            self.backend.stop()
        except Exception:
            pass
        self._stop_log_tails()
        self._stop_poller()
        try:
            self._cleanup_orphans()
        except Exception:
            pass
        self.root.destroy()


# ---------- entry point -----------------------------------------------------


def main() -> int:
    if not is_admin():
        # Re-launch with UAC prompt. The current process exits.
        relaunch_as_admin()
        return 0
    root = tk.Tk()
    TrackerApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
