"""Tiny throughput benchmark for the native ETW capture engine.

Usage (from repo root, ELEVATED shell):

    python bench/throughput.py --duration 5

Generates 10k file create+delete cycles in a temp dir while a CaptureService
is running, then reports events/sec received.
"""

from __future__ import annotations

import argparse
import os
import tempfile
import threading
import time
from pathlib import Path

from service.capture_service import (
    CaptureService,
    CaptureTarget,
    _native_binary_path,
    is_admin,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--duration", type=float, default=5.0, help="seconds to run"
    )
    parser.add_argument(
        "--ops", type=int, default=10000, help="file ops to generate"
    )
    args = parser.parse_args()

    if not is_admin():
        print("error: must run as Administrator")
        return 2
    if _native_binary_path() is None:
        print(
            "error: native binary not built. "
            "Run cmake --build service/native/build"
        )
        return 2

    received: list[dict] = []
    lock = threading.Lock()

    def on_event(payload: dict) -> None:
        with lock:
            received.append(payload)

    target = CaptureTarget(exe_path=__file__, pid=os.getpid())
    svc = CaptureService(target, on_event)
    svc.start()
    print(f"capture started; running for {args.duration}s, {args.ops} ops")

    start = time.monotonic()
    tmp_dir = Path(tempfile.mkdtemp(prefix="tracker-bench-"))
    try:
        for i in range(args.ops):
            if time.monotonic() - start > args.duration:
                break
            p = tmp_dir / f"f{i}.tmp"
            p.write_bytes(b"x")
            p.unlink(missing_ok=True)
        elapsed = time.monotonic() - start
        # Drain a bit longer so events still in flight reach the callback.
        time.sleep(1.0)
    finally:
        svc.stop()
        for f in tmp_dir.glob("*"):
            f.unlink(missing_ok=True)
        tmp_dir.rmdir()

    with lock:
        n = len(received)
    by_kind: dict[str, int] = {}
    for e in received:
        kind = e.get("kind", "?")
        by_kind[kind] = by_kind.get(kind, 0) + 1
    rate = n / elapsed if elapsed > 0 else 0
    print(f"\nreceived {n} events in {elapsed:.2f}s = {rate:.0f} events/sec")
    print("by kind:", by_kind)
    print("stats:", svc.stats())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
