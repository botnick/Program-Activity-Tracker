# คู่มือใช้งาน Activity Tracker (ภาษาไทย)

ระบบติดตามกิจกรรมของโปรเซสบน Windows แบบเรียลไทม์
จับการอ่าน/เขียนไฟล์ ทุกชนิด รวมถึง AppData, การแก้ Registry, การ spawn ลูก process,
และการเชื่อมต่อเครือข่าย — เห็นทุกอย่างผ่านเว็บเบราว์เซอร์

---

## 1. สิ่งที่ต้องมีก่อนใช้งาน

| รายการ | เวอร์ชันขั้นต่ำ | หมายเหตุ |
|---|---|---|
| Windows | 10 / 11 (x64) | ETW เปิดมากับระบบ ไม่ต้องลงเพิ่ม |
| Python | 3.10 ขึ้นไป | ติ๊ก "Add to PATH" ตอนติดตั้ง |
| Node.js | 20 ขึ้นไป | สำหรับ build UI (ครั้งแรกครั้งเดียว) |
| สิทธิ์ Admin | จำเป็น | ETW kernel providers ต้องการ Administrator |

> ถ้าไม่มี Node.js ก็ยังรันได้ แต่จะไม่มี UI หน้าเว็บ (ใช้ API ผ่าน curl/Postman ได้)

---

## 2. เริ่มใช้งานครั้งแรก (One-Click)

1. เปิดโฟลเดอร์ `C:\Users\btx\Desktop\kuy`
2. **ดับเบิลคลิก `start.bat`**
3. Windows จะถาม UAC (ยืนยัน Administrator) → กด **Yes**
4. หน้าต่าง CMD ใหม่จะเปิดขึ้น โดยจะ:
   - ติดตั้ง Python deps อัตโนมัติ (ครั้งแรกใช้เวลา ~1 นาที)
   - Build native ETW binary ด้วย CMake/MSVC อัตโนมัติถ้ายังไม่มี (~10 วินาที)
   - Build UI ด้วย npm (ครั้งแรกใช้เวลา ~30 วินาที)
   - เริ่ม backend ที่ `http://127.0.0.1:8000`
   - เปิดเบราว์เซอร์ให้อัตโนมัติหลัง 3 วินาที
5. เมื่อเห็นแถบสีเขียว `admin: yes` ที่มุมบนขวา → พร้อมใช้งาน

ปิดระบบ: ปิดหน้าต่าง CMD หรือดับเบิลคลิก `stop.bat`

### 2.1 (ครั้งเดียว) ตั้ง Defender exclusion เพื่อไม่ให้ scan native binary

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup-defender-exclusion.ps1
```
สคริปต์จะขอ UAC แล้ว exclude path `service\native\build` + process `tracker_capture.exe` —
ป้องกัน Defender quarantine ตอน build / รัน. ไม่จำเป็นถ้า Defender ปิดอยู่แล้ว

---

## 3. วิธีติดตามโปรแกรม (เช่น `xdt.exe`)

### 3.1 เลือก process ที่กำลังรันอยู่

1. เปิดโปรแกรมเป้าหมาย (เช่น `xdt.exe`) ก่อน
2. ในเว็บ UI ช่อง **"Pick a running process"** ทางซ้าย พิมพ์ `xdt`
3. คลิกที่รายการที่ขึ้นมา → ระบบจะเริ่ม session ทันที

### 3.2 หรือเลือกจาก path ของ exe

ถ้า process ยังไม่ได้รัน เปิดโปรแกรมก่อน แล้วใช้ช่อง "or by exe path"
ใส่ path เต็มของ `.exe` แล้วกด **Track**

### 3.3 ดูเหตุการณ์ realtime

- ตารางตรงกลางจะแสดงทุก event ที่เกิดขึ้นแบบสด ๆ:
  - **file**: เปิด/อ่าน/เขียน/ลบ/เปลี่ยนชื่อไฟล์ (รวม `AppData`, `Temp`, ทุกที่)
  - **registry**: สร้าง/แก้/ลบ key หรือ value
  - **process**: ตัว target spawn ลูก process ใหม่
  - **network**: เชื่อมต่อ TCP/UDP, ส่ง/รับข้อมูล
- ระบบจะ **track ลูกหลาน** ของ process อัตโนมัติ — ถ้า `xdt.exe` รัน `helper.exe`, helper.exe ก็ถูก track ด้วย

### 3.4 ฟิลเตอร์ + ค้นหา

- กดชิป `file` / `registry` / `process` / `network` เพื่อเปิดปิดหมวด
- ช่อง search: พิมพ์ `AppData` เพื่อดูเฉพาะกิจกรรมในโฟลเดอร์นั้น
- Time range: `30s` / `5min` / `1h` / `All` / `Live` (default)

### 3.5 ดูรายละเอียด event

คลิกที่แถวใด ๆ → drawer จะเปิดด้านขวา แสดง:
- Path เต็ม + ปุ่มคัดลอก
- PID / PPID
- JSON `details` แบบ pretty-printed
- ปุ่ม "Open file location" (สำหรับไฟล์)

### 3.6 Export ข้อมูล

ปุ่มมุมขวาบน:
- **CSV**: เปิดด้วย Excel ได้เลย
- **JSONL**: ใช้กับเครื่องมือวิเคราะห์ภายนอก

### 3.7 ดู Logs realtime (Tab Logs)

UI มี 2 tab: **Events** (default) และ **Logs**. กด tab "Logs" เพื่อดู log file ของระบบ:

| Stream | บอกอะไร |
|---|---|
| `tracker` | Log รวมทั้งหมด (ทุกระดับ) |
| `events` | Log เฉพาะ event ingestion |
| `requests` | HTTP request trace (มี trace_id, duration) |
| `errors` | WARNING+ จากทุก logger รวมไว้ |
| `native` | stderr ของ `tracker_capture.exe` แยกเป็นไฟล์ของตัวเอง |

แต่ละ log file เก็บใน `logs/` ขนาดสูงสุด 50MB × 3 backup = 150MB ต่อ stream
มี search box, level filter, live-tail toggle — ดูได้แบบ realtime ผ่าน WebSocket

### 3.8 Performance — ออกแบบไม่ให้กระตุก

ที่ rate **1000 events/sec** UI ยัง smooth เพราะ:
- WS messages ทุกตัวสะสมใน ref → flush ครั้งเดียวต่อ animation frame (60Hz max)
- Auto-scroll throttle 1 reflow/frame → ไม่มี layout thrashing
- Sparkline update 1Hz ไม่ใช่ 60Hz
- Drawer ไม่ mount/unmount → slide-in/out ผ่าน CSS transition
- ทุก component memoized — re-render เฉพาะที่จำเป็น
- Process list diff-update — รายการที่ไม่เปลี่ยนคงไว้เดิม ไม่ flicker

---

## 4. โครงสร้างที่จับเหตุการณ์ (Capture Engine)

ระบบมี 2 backends สลับได้ผ่าน env var `TRACKER_CAPTURE_ENGINE`:

| ค่า | ใช้อะไร | ข้อดี |
|---|---|---|
| `auto` (ค่าเริ่มต้น) | C++ native ถ้ามี ไม่งั้น Python | ฉลาดที่สุด |
| `native` | `service\native\build\tracker_capture.exe` | เร็วสุด ไม่ติด GIL |
| `python` | `pywintrace` library | fallback ถ้า native build ไม่ได้ |

### Build native engine (ทางเลือก เพื่อประสิทธิภาพสูงสุด)

ต้องมี Visual Studio 2022 หรือใหม่กว่า ที่ลง C++ workload

```cmd
:: เปิด "x64 Native Tools Command Prompt for VS"
cd C:\Users\btx\Desktop\kuy
"%VSINSTALLDIR%\Common7\Tools\VsDevCmd.bat" -arch=amd64
cmake -S service\native -B service\native\build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build service\native\build --config Release
```

ผลลัพธ์: `service\native\build\tracker_capture.exe` (~100 KB)
หลังจากนี้ ระบบจะใช้ native โดยอัตโนมัติ

---

## 5. แก้ไขปัญหา (Troubleshooting)

### ❌ "Backend is not Administrator; ETW capture disabled"

**สาเหตุ**: รัน backend ด้วยสิทธิ์ user ปกติ ETW kernel providers ต้องการ admin

**แก้**: ปิด backend แล้ว **ดับเบิลคลิก `start.bat`** ใหม่ (จะขอ UAC อัตโนมัติ)
หรือเปิด PowerShell แบบ admin แล้วรัน `.\run-elevated.ps1`

---

### ❌ Session แสดง `capture: needs_admin` แม้ run ผ่าน `start.bat`

**สาเหตุ**: UAC ถูกปฏิเสธ หรือ Group Policy บังคับให้รัน non-admin

**แก้**: คลิกขวาที่ `start.bat` → **Run as administrator**

---

### ❌ ไม่เห็น event ใด ๆ เลย

**ตรวจสอบ**:
1. แถบ admin มุมบนขวาเป็นสีเขียว `admin: yes` หรือยัง
2. Process เป้าหมายยังรันอยู่ (อาจปิดไปแล้วโดยไม่รู้)
3. กดชิปทุกหมวด (file/registry/process/network) ให้เปิดทั้งหมด
4. ดู `http://127.0.0.1:8000/metrics` ว่า `tracker_events_total > 0` ไหม
   ถ้าเป็น 0 แสดงว่า ETW ยังไม่ได้รับ event เลย

**ทดสอบ**: ลองทำกิจกรรมให้ target process — เช่น เปิดแล้วปิด Notepad,
หรือสำหรับ `xdt.exe` ลองคลิกเมนู / save file

---

### ❌ Native engine ไม่ทำงาน (`tracker_capture.exe` crash หรือ exit code 5)

**สาเหตุ**: Exit code 5 = `ERROR_ACCESS_DENIED` — ไม่ได้รัน admin

**แก้**: ใช้ `start.bat` (auto-elevate) แทนการรัน .exe ตรง ๆ
ถ้าต้องการ debug: บังคับใช้ Python backend แทน
```cmd
set TRACKER_CAPTURE_ENGINE=python
start.bat
```

---

### ❌ Port 8000 ถูกใช้แล้ว

**สาเหตุ**: มีโปรเซสค้างอยู่ หรือใช้ port กับอย่างอื่น

**แก้**: ดับเบิลคลิก `stop.bat` ให้ฆ่าทุก process บน port 8000 แล้วรัน `start.bat` ใหม่
หรือเปลี่ยน port: `set TRACKER_PORT=8001` ก่อนรัน

---

### ❌ UI ขึ้น "ui not built"

**สาเหตุ**: ยังไม่ได้ build UI

**แก้**: `start.bat` จะ build ให้อัตโนมัติ ถ้ายังไม่ได้ ให้รัน:
```cmd
cd ui
npm install
npm run build
```

---

## 6. ใช้กับ Claude (MCP)

ระบบมี MCP server ให้ Claude Code / Claude Desktop ช่วยวิเคราะห์ session ได้

### ตั้งค่า Claude Code

ไฟล์ `.mcp.json` มีอยู่แล้วในโฟลเดอร์โปรเจกต์ — Claude Code จะอ่านอัตโนมัติ
พิมพ์ `/mcp` ใน Claude Code เพื่อดู 14 tools ที่ใช้ได้:

| Tool | ใช้ทำอะไร |
|---|---|
| `list_processes` | ดู process ที่รันอยู่ |
| `start_session` | เริ่ม track |
| `query_events` | ค้น event แบบ filter |
| `search_events` | ค้น substring |
| `summarize_session` | สรุปกิจกรรมทั้ง session |
| `export_session` | export เป็นไฟล์ลง Downloads |
| ... | อีก 8 tools |

### ตั้งค่า Claude Desktop

แก้ `%APPDATA%\Claude\claude_desktop_config.json`:

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

รีสตาร์ท Claude Desktop → activity-tracker จะปรากฏในเมนูเครื่องมือ

### ตัวอย่างคำสั่งกับ Claude

- *"ใช้ activity-tracker ดูว่า xdt.exe เขียนอะไรลง AppData บ้าง"*
- *"summarize session ล่าสุด — มีไฟล์อะไรเปลี่ยนแปลง, registry ไหนถูกแก้"*
- *"export session นั้นเป็น CSV ให้หน่อย"*

---

## 7. สถาปัตยกรรม (สั้น ๆ)

```
xdt.exe (target) ──┐
                   │  ETW kernel events
                   ▼
        ┌──────────────────────┐
        │  CaptureService      │  Python หรือ C++ native
        │  (admin-required)    │
        └──────────┬───────────┘
                   │  on_event()
                   ▼
        ┌──────────────────────┐
        │  EventHub + SQLite   │  ring buffer + WAL persistent
        └──────────┬───────────┘
                   │  WebSocket
                   ▼
        ┌──────────────────────┐         ┌────────────────┐
        │  Web UI (React)      │ ◄─HTTP─ │  MCP server    │ ──► Claude
        │  http://127.0.0.1:   │         │  (stdio)       │
        │       8000           │         └────────────────┘
        └──────────────────────┘
```

ดูรายละเอียดเพิ่มเติม: `docs/architecture.md`, `docs/operations.md`, `docs/threat-model.md`

---

## 8. Environment Variables (ปรับแต่ง)

| ตัวแปร | ค่าเริ่มต้น | คำอธิบาย |
|---|---|---|
| `TRACKER_BIND_HOST` | `127.0.0.1` | host ที่ฟัง (อย่าตั้งเป็น 0.0.0.0 เพราะไม่มี auth) |
| `TRACKER_PORT` | `8000` | port |
| `TRACKER_DB_PATH` | `events.db` | path ของ SQLite |
| `TRACKER_EVENT_RING_SIZE` | `50000` | ขนาด ring buffer per session |
| `TRACKER_FILE_OBJECT_CACHE_SIZE` | `100000` | LRU cap ของ FileObject→path map |
| `TRACKER_LOG_DIR` | `logs` | โฟลเดอร์ log |
| `TRACKER_LOG_LEVEL` | `INFO` | ระดับ log |
| `TRACKER_CAPTURE_ENGINE` | `auto` | `auto` / `native` / `python` |

ตั้งค่าใน CMD ก่อนรัน:
```cmd
set TRACKER_CAPTURE_ENGINE=native
set TRACKER_LOG_LEVEL=DEBUG
start.bat
```

---

## 9. ขอความช่วยเหลือ

- ปัญหา/bug → เปิด issue ที่ repo
- ดู logs: `logs\tracker.log` (JSON-line format)
- ดู metrics สด: `http://127.0.0.1:8000/metrics`
- ดู health: `http://127.0.0.1:8000/api/health`

แก้ปัญหาส่วนใหญ่ด้วยลำดับนี้:
1. `stop.bat`
2. ปิดหน้าต่าง CMD ทั้งหมด
3. `start.bat` (Run as administrator)
4. ถ้ายังไม่หาย: ดู `logs\tracker.log` แล้วส่งให้คนช่วย
