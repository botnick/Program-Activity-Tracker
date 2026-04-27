# tracker_capture (native ETW engine)

Native C++ replacement for the `pywintrace`-based ETW backend used by
`service/capture_service.py`. Subscribes to the same four kernel providers
(File / Registry / Process / Network), filters by PID + descendants, and
emits one JSON object per line on stdout for the Python supervisor to
ingest.

## Build

Requires Visual Studio 2026 Community (with the Desktop C++ workload and
the Windows SDK) and CMake. CMake is bundled with VS at
`Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe`.

From a Developer Command Prompt (or any shell that has run
`VsDevCmd.bat -arch=amd64`), at the repo root:

```
cmake -S service\native -B service\native\build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build service\native\build --config Release
```

If Ninja isn't available, fall back to the bundled VS generator:

```
cmake -S service\native -B service\native\build -G "Visual Studio 17 2022" -A x64
cmake --build service\native\build --config Release
```

One-liner from outside the dev shell:

```
cmd /c '"C:\Program Files\Microsoft Visual Studio\18\Community\Common7\Tools\VsDevCmd.bat" -arch=amd64 && cmake -S service\native -B service\native\build -G Ninja -DCMAKE_BUILD_TYPE=Release && cmake --build service\native\build --config Release'
```

The resulting executable lives at one of:

- `service\native\build\tracker_capture.exe`        (Ninja)
- `service\native\build\Release\tracker_capture.exe` (VS multi-config)

The Python supervisor (`service/capture_service.py`) probes both paths.

## Usage

```
tracker_capture.exe --pid <int> [--pid-create-time <epoch_ms>]
                    [--engines file,registry,process,network]
                    [--session-name <name>]
                    [--no-orphan-cleanup]
```

Outputs newline-delimited JSON on stdout (one event per line). Logs and
errors go to stderr only.

## Selecting the engine from Python

The default backend selection is `auto`: if `tracker_capture.exe` exists,
it is used; otherwise the supervisor falls back to `pywintrace`. To
override:

```
set TRACKER_CAPTURE_ENGINE=native    # require native, fail if missing
set TRACKER_CAPTURE_ENGINE=python    # force pywintrace fallback
set TRACKER_CAPTURE_ENGINE=auto      # default
```

The `capture_engine` setting in `backend/app/config.py` is the same knob
without the env-var prefix.

## Troubleshooting

- **Permission denied / cannot start trace.** ETW kernel providers
  require Administrator. Restart the supervising process from an
  elevated shell.
- **`ERROR_ALREADY_EXISTS` on session name.** A prior crashed run left
  a session active. The binary auto-sweeps any session whose name
  matches its prefix at startup; pass `--no-orphan-cleanup` to skip.
- **Antivirus quarantine.** The exe enables real-time kernel ETW, which
  some EDR products flag. Whitelist `service\native\build\` if needed.
- **Build failure: `tdh.h` not found.** Ensure the Windows SDK is
  installed via the VS installer (component "Windows 11 SDK"). Re-run
  `VsDevCmd.bat -arch=amd64` so `INCLUDE` / `LIB` are populated.
