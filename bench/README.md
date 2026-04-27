# Benchmarks

`throughput.py` measures end-to-end events/sec for the native ETW capture
engine.

## Run

From an **elevated** shell:

```
python bench/throughput.py --duration 5 --ops 10000
```

This spawns a CaptureService against the benchmark process itself, hammers
a temp directory with file create/delete cycles for `--duration` seconds,
and reports events received per second plus a histogram by kind.

## Interpreting

- A baseline NVMe-equipped Windows 10 box should comfortably hit 5k-20k
  events/sec at this workload.
- If `dropped` in stats is non-zero, the asyncio publish queue was over-full
  - increase `TRACKER_SUBSCRIBER_QUEUE_SIZE`.
- If `errors` keeps climbing, the native binary is logging warnings - check
  the `[error]` lines on stderr.

This is NOT part of the test suite; it's not run in CI.
