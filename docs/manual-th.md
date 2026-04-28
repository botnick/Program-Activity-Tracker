# คู่มือใช้งาน Activity Tracker (ภาษาไทย)

ระบบติดตามกิจกรรมของโปรเซสบน Windows แบบเรียลไทม์ — เห็นทุก op ของไฟล์ / registry / process / network
ของ target.exe และลูกหลานทุกตัว ไม่ inject DLL ไม่ hook API ใช้ ETW kernel ตรง ๆ
(ระดับเดียวกับ Procmon / Sysmon)

---

## 1. สิ่งที่ต้องมีก่อนใช้งาน

มี 2 ทางเลือก: **(A)** โหลด release zip มาใช้เลย หรือ **(B)** clone source มา build เอง

### A. ใช้ release zip (แนะนำสำหรับผู้ใช้ทั่วไป)

| รายการ | เวอร์ชันขั้นต่ำ | หมายเหตุ |
|---|---|---|
| Windows | 10 / 11 (x64) | ETW เปิดมากับระบบ |
| สิทธิ์ Admin | จำเป็น | ETW kernel providers ต้องการ Administrator |

ไม่ต้องลง Python / Node.js / Visual Studio — bundle มาในซิปแล้ว

### B. Build จาก source (สำหรับ developer)

| รายการ | เวอร์ชันขั้นต่ำ |
|---|---|
| Windows | 10 / 11 (x64) |
| Python | 3.10 ขึ้นไป (ติ๊ก "Add to PATH" ตอนติดตั้ง) |
| Node.js | 20 ขึ้นไป |
| Visual Studio 2022+ | C++ workload |
| Administrator | จำเป็น |

---

## 2. เริ่มใช้งานครั้งแรก

### 2.A วิธี release zip (one-click)

1. โหลด `ActivityTracker-vX.Y.Z.zip` จาก [GitHub Releases](https://github.com/botnick/Program-Activity-Tracker/releases)
2. แตก zip ไปที่ไหนก็ได้ (เช่น `C:\Tools\ActivityTracker`)
3. **ดับเบิลคลิก `tracker.exe`** ในโฟลเดอร์ที่แตก
4. Windows ถาม UAC → กด **Yes**
5. หน้าต่าง GUI เปิดมา → กดปุ่ม **Start**
   - tracker.exe จะ spawn backend uvicorn เป็น subprocess
   - เบราว์เซอร์จะเปิด `http://127.0.0.1:8000` อัตโนมัติเมื่อพร้อม
6. เลือก process จาก process picker → กด **Start capture**

ปิดระบบ: กดปุ่ม **Stop** ในโปรแกรม หรือปิดหน้าต่าง tracker.exe (มันจะ cleanup tracker_capture.exe + ETW sessions ให้อัตโนมัติ)

### 2.B วิธี source / dev (one-click)

1. เปิดโฟลเดอร์โปรเจกต์
2. **ดับเบิลคลิก `start.bat`**
3. Windows ถาม UAC → กด **Yes**
4. หน้าต่าง CMD ใหม่จะ:
   - ติดตั้ง Python deps อัตโนมัติ (~1 นาที)
   - Build native ETW binary ผ่าน CMake/MSVC (~10 วินาที)
   - Build UI ผ่าน npm (~30 วินาที)
   - เริ่ม backend ที่ `http://127.0.0.1:8000`
   - เปิดเบราว์เซอร์ให้อัตโนมัติหลัง 3 วินาที
5. เห็นแถบสีเขียว `admin: yes` ที่มุมบนขวา = พร้อม

ปิดระบบ: ปิดหน้าต่าง CMD หรือดับเบิลคลิก `stop.bat`

### 2.C ฟีเจอร์ใน tracker.exe (release เท่านั้น)

- **Capture monitor tab** — เห็น pid / uptime / ETW session ของ `tracker_capture.exe`, KPI 8 ตัว (events/sec, total, tracked pids, cache, CPU, RAM, threads, handles), live sparkline 60 วินาที (events/sec / CPU / RAM), per-kind bar chart (file / registry / process / network)
- **Backend / Events / Errors / Native log tabs** — live tail พร้อม ANSI color, search box, auto-scroll, save / clear / copy
- **Start / Stop / Restart buttons** + Open browser shortcut + Open folder shortcut
- **F5** = restart, **Ctrl+Q** = quit, **Ctrl+F** = search, **Ctrl+L** = clear, **Ctrl+S** = save logs

### 2.1 ตั้ง Defender exclusion (ครั้งเดียว แนะนำ)

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup-defender-exclusion.ps1
```

สคริปต์ขอ UAC แล้วเพิ่ม exclusion ให้ folder `service\native\build`
และ process `tracker_capture.exe` — ป้องกัน Defender quarantine ตอน build/รัน

### 2.2 ย้ายไปใช้บน PC เครื่องอื่น

โปรเจกต์ self-contained — clone ไปเครื่องอื่นแล้ว double-click `start.bat` พอ
ทุกอย่างจะ build จาก source ใหม่อัตโนมัติ. ไม่มี hardcoded path ที่ผูกกับเครื่องเดิม

```cmd
git clone <repo-url> C:\path\activity-tracker
cd C:\path\activity-tracker
:: ติดตั้ง prerequisites ตามตารางข้อ 1
start.bat
```

ถ้าต้องการ pin version dependency ให้ตรงเป๊ะ:
```cmd
python -m pip install -r requirements-lock.txt
```

---

## 3. วิธีติดตามโปรแกรม (เช่น `xdt.exe`)

### 3.1 เลือก process ที่กำลังรันอยู่

1. เปิดโปรแกรมเป้าหมาย (เช่น `xdt.exe`)
2. ในเว็บ UI ช่อง **"Pick a running process"** ทางซ้าย พิมพ์ `xdt`
3. คลิกที่รายการที่ขึ้นมา (จะเห็น icon จริงของโปรแกรม) → ระบบเริ่ม session ทันที

### 3.2 หรือเลือกจาก path ของ exe

ใส่ path เต็มของ `.exe` แล้วกด **Track**
(ต้องมี process ที่ตรง path นี้รันอยู่)

### 3.3 ดูเหตุการณ์ realtime

ตารางตรงกลางแสดงทุก event ที่เกิดขึ้นแบบสด ๆ พร้อม icon + chip สี:
- **file** — เปิด / อ่าน / เขียน / ลบ / เปลี่ยนชื่อไฟล์
- **registry** — สร้าง / แก้ / ลบ key หรือ value
- **process** — target spawn ลูก process ใหม่ (ลูกใหม่ก็ถูก track ทันที)
- **network** — TCP/UDP send / receive / connect

### 3.4 ครอบคลุมทุก path ทุก drive

| target เขียนที่ไหน | UI แสดงเป็น |
|---|---|
| `D:\file\eiei\out.bin` | `D:\file\eiei\out.bin` |
| `C:\Users\n\Desktop\kiano_recovery\log.txt` | `C:\Users\n\Desktop\kiano_recovery\log.txt` |
| `C:\Users\n\Documents\report.docx` | `C:\Users\n\Documents\report.docx` |
| `%APPDATA%\xdt\config.json` | `C:\Users\n\AppData\Roaming\xdt\config.json` |
| `\\fileserver\share\backup.zip` | `\\fileserver\share\backup.zip` |
| USB stick `E:\photo.jpg` | `E:\photo.jpg` |
| `C:\$Recycle.Bin\...` | `C:\$Recycle.Bin\...` |

ไม่ hardcode path ใด ๆ — ระบบสร้าง drive-letter map ผ่าน `QueryDosDeviceW` ที่เครื่องเอง

### 3.5 Filter + ค้นหา

- ชิป `file` / `registry` / `process` / `network` เปิด-ปิดหมวด
- ช่อง search: substring match ทุก path / target / operation / details
- Time range: `Live` / `30s` / `5min` / `1h` / `All`
- Pause/Resume: หยุดการเลื่อนชั่วคราว ช่วงนี้ event buffer ไว้ที่ฝั่ง client

### 3.6 Drawer รายละเอียด event

คลิกแถวใด ๆ → drawer slide จากขวา แสดง:
- Path เต็ม + ปุ่มคัดลอก
- PID / PPID
- JSON `details` แบบ pretty-printed
- ปุ่ม "Open file location" สำหรับไฟล์

### 3.7 Export

ปุ่มมุมขวาบน:
- **CSV** เปิดด้วย Excel ได้เลย
- **JSONL** สำหรับเครื่องมือวิเคราะห์ภายนอก

### 3.8 Tab Logs

ปุ่ม **Logs** ที่ส่วน header สลับไปดู log stream ของระบบ:

| Stream | ข้อมูล |
|---|---|
| `tracker` | log รวมทุกระดับ |
| `events` | log การ ingest event |
| `requests` | HTTP request trace (มี trace_id, duration) |
| `errors` | WARNING+ จากทุก logger รวมไว้ |
| `native` | stderr ของ `tracker_capture.exe` |

แต่ละไฟล์เก็บใน `logs/` ขนาดสูงสุด 50MB × 3 backup = 150MB ต่อ stream
มี search, level filter, live-tail toggle (WebSocket)

### 3.9 Performance — ออกแบบไม่ให้กระตุก

ที่ rate **1000 events/sec** ขึ้นไป UI ยัง smooth เพราะ:
- WS messages ทุกตัวสะสมใน ref → flush ครั้งเดียวต่อ animation frame (≤60Hz)
- Auto-scroll throttle 1 reflow/frame → ไม่มี layout thrashing
- Sparkline update 1 Hz ไม่ใช่ 60 Hz
- Drawer ไม่ mount/unmount → slide ผ่าน CSS transition
- ทุก component memoized — re-render เฉพาะที่จำเป็น
- Process list diff-update — แถวที่ไม่เปลี่ยนคงไว้ ไม่ flicker

---

## 4. ใช้ MCP server กับ AI client

ระบบมี MCP server (`activity-tracker-mcp`) — 14 tools / 6 resources / 4 prompts ผ่าน stdio
ใช้ได้กับ AI client ทุกตัวที่ implement MCP standard:

- Claude Code, Claude Desktop
- Cursor IDE
- Continue (VS Code / JetBrains extension)
- Cline (VS Code extension)
- Windsurf (Codeium IDE)
- Goose (Block / Square)
- Zed editor
- MCP Inspector (debug)

**วิธี config สำหรับแต่ละ client มีให้ครบใน Tab "MCP How-To" บนเว็บ UI** (มีปุ่ม Copy ให้กด) — ดูตอนเปิด `tracker.exe` แล้วกดเข้า browser

### 4.1 Quick start (ทั่วไป)

ทุก client ใช้ shape JSON เดียวกัน:

```json
{
  "mcpServers": {
    "activity-tracker": {
      "command": "python",
      "args": ["-m", "mcp_tracker"],
      "env": { "MCP_TRACKER_URL": "http://127.0.0.1:8000" }
    }
  }
}
```

ถ้าใช้ release zip → ใช้ python ที่ bundle มาให้แทน:

```json
"command": "C:\\path\\to\\release\\python\\python.exe"
```

### 4.2 Tools หลัก ๆ

| Tool | ใช้ทำอะไร |
|---|---|
| `list_processes` | ดู process ที่รันอยู่ |
| `start_session` | เริ่ม track โดยให้ pid หรือ exe_path |
| `query_events` | filter + paginate event |
| `search_events` | substring search |
| `tail_events` | poll-based live tail |
| `summarize_session` | สรุปกิจกรรม (counts / top paths / pids / time bounds) |
| `export_session` | export CSV/JSONL ลง Downloads |
| `get_capture_stats` | ETW stats per session |
| `get_metrics` | raw Prometheus metrics |

### 4.3 ตัวอย่าง prompt

- *"ใช้ activity-tracker ดูว่า xdt.exe เขียนอะไรลง AppData บ้าง"*
- *"summarize session ล่าสุด — มีไฟล์อะไรเปลี่ยนแปลง, registry ไหนถูกแก้"*
- *"export session นั้นเป็น CSV ให้หน่อย"*
- *"compare session A กับ B"*

---

## 5. แก้ไขปัญหา (Troubleshooting)

### Problem: "Backend is not Administrator; ETW capture disabled"

**สาเหตุ**: รัน backend ด้วย user ปกติ
**แก้**: ปิด backend แล้ว double-click `start.bat` ใหม่ (จะขอ UAC)

### Problem: Session แสดง `capture: needs_admin` แม้ run ผ่าน start.bat

**สาเหตุ**: UAC ถูก deny
**แก้**: คลิกขวาที่ `start.bat` → **Run as administrator**

### Problem: ไม่เห็น event ใด ๆ เลย

**ตรวจสอบ**:
1. แถบ admin มุมบนขวาเป็นสีเขียว `admin: yes` หรือยัง
2. Process เป้าหมายยังรันอยู่หรือไม่
3. กดชิปทุกหมวด (file/registry/process/network) ให้เปิด
4. ดู `http://127.0.0.1:8000/metrics` ว่า `tracker_events_total > 0` ไหม
5. ดู Tab Logs → stream `native` มี error อะไรไหม

### Problem: Native binary missing — RuntimeError ตอน start session

**สาเหตุ**: Visual Studio ไม่ได้ติดตั้ง C++ workload หรือ build ล้มเหลว
**แก้**:
1. ติดตั้ง VS 2022/2026 + Desktop development with C++ workload
2. ลบ `service\native\build` ทิ้ง
3. รัน `start.bat` ใหม่ — มันจะ build ให้

### Problem: Defender quarantine `tracker_capture.exe`

**แก้**: รัน `scripts\setup-defender-exclusion.ps1` (ข้อ 2.1)

### Problem: Port 8000 ถูกใช้แล้ว

**แก้**: `stop.bat` ฆ่าทุก process บน port 8000 แล้วรัน `start.bat` ใหม่
หรือเปลี่ยน port: `set TRACKER_PORT=8001 && start.bat`

### Problem: UI ขึ้น "ui not built"

**แก้**: `cd ui && npm install && npm run build`

---

## 6. โครงสร้างโปรเจกต์

```
activity-tracker/
├── start.bat / stop.bat / run-elevated.ps1   ← ตัวเริ่ม-หยุดระบบ
├── bootstrap.ps1                             ← ติดตั้ง deps + build ทั้งหมด
├── scripts/setup-defender-exclusion.ps1      ← AV exclusion
├── pyproject.toml / requirements-lock.txt    ← Python deps
│
├── backend/app/                              ← FastAPI control plane
├── service/                                  ← capture layer
│   ├── capture_service.py                    ← Python orchestrator (thin)
│   └── native/                               ← C++ ETW engine + .ico + .rc
├── ui/                                       ← React + Vite + Tailwind
├── mcp/                                      ← MCP server package
│
├── tests/ + bench/                           ← 99 tests + throughput bench
├── docs/                                     ← architecture / operations / threat-model / manual-th
└── CLAUDE.md                                 ← guide สำหรับ Claude Code
```

---

## 7. Environment Variables

ตั้งใน CMD ก่อนรัน หรือใน `.env` ที่โฟลเดอร์โปรเจกต์

| ตัวแปร | Default | ความหมาย |
|---|---|---|
| `TRACKER_BIND_HOST` | `127.0.0.1` | host ที่ฟัง (อย่าตั้ง 0.0.0.0 — ไม่มี auth) |
| `TRACKER_PORT` | `8000` | port |
| `TRACKER_DB_PATH` | `events.db` | path SQLite |
| `TRACKER_DB_RETENTION_DAYS` | `30` | ลบ event เก่ากว่า N วัน (`0` = ปิด retention) |
| `TRACKER_EVENT_RING_SIZE` | `50000` | ขนาด ring buffer per session |
| `TRACKER_FILE_OBJECT_CACHE_SIZE` | `100000` | LRU cap ของ FileObject→path map |
| `TRACKER_LOG_DIR` | `logs` | โฟลเดอร์ log |
| `TRACKER_LOG_LEVEL` | `INFO` | ระดับ log |

---

## 8. สถาปัตยกรรม (สั้น ๆ)

```
xdt.exe (target) ──┐
                   │  ETW kernel events (4 providers, no inject/no hook)
                   ▼
        ┌──────────────────────┐
        │  tracker_capture.exe │  C++ native, NDJSON to stdout
        │  (admin-required)    │
        └──────────┬───────────┘
                   │  hello sentinel + events + 1Hz heartbeat
                   ▼
        ┌──────────────────────┐
        │  capture_service.py  │  thin Python subprocess wrapper
        └──────────┬───────────┘
                   │  on_event() callback
                   ▼
        ┌──────────────────────┐
        │  EventHub + SQLite   │  ring buffer + WAL persistent + 30-day retention
        └──────────┬───────────┘
                   │  WebSocket broadcast
                   ▼
        ┌──────────────────────┐         ┌────────────────┐
        │  Web UI (React)      │ ◀─HTTP─ │  MCP server    │ ──▶ Claude
        │  http://127.0.0.1    │         │  (stdio)       │
        │       :8000          │         └────────────────┘
        └──────────────────────┘
```

ดูเพิ่ม: `docs/architecture.md`, `docs/operations.md`, `docs/threat-model.md`

---

## 9. ปลอดภัยไหม

- **ไม่ inject DLL** ใส่ target (ไม่แตะ exe)
- **ไม่ hook API** (ไม่แทน SSDT entry)
- **ไม่ load driver ของเรา** (ใช้ ETW infrastructure ที่ kernel มีอยู่แล้ว)
- **Read-only observation** — kernel emit event ไป เราเป็น passive consumer
- ผลข้างเคียง: load CPU/IO บน kernel ETW subsystem ระดับเดียวกับ Procmon (ต่ำมาก)

---

## 10. ขอความช่วยเหลือ

- Logs สด: `http://127.0.0.1:8000` → tab Logs
- Metrics: `http://127.0.0.1:8000/metrics`
- Health: `http://127.0.0.1:8000/api/health`
- Log files: `logs/{tracker,events,requests,errors,native}.log`

แก้ปัญหาส่วนใหญ่ด้วยลำดับนี้:
1. `stop.bat`
2. ปิด CMD ทุกหน้าต่าง
3. `start.bat` (Run as administrator)
4. ถ้ายังไม่หาย: เปิด Tab Logs → stream `errors` → ดูบรรทัดล่าสุด
