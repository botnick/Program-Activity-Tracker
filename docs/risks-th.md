# Risk Register — Activity Tracker

เอกสารระบุความเสี่ยงหลักของระบบและสิ่งที่ทำไปแล้วเพื่อลดความเสี่ยง

ตารางจัดเรียงจากระดับความรุนแรงสูงสุดลงไป

---

## 🔴 ความเสี่ยงสูง (มีผลโดยตรงต่อความน่าเชื่อถือ / data loss / ความปลอดภัย)

### R1 · Antivirus / EDR ขึ้น flag ตัว `tracker_capture.exe`
**ทำไมเสี่ยง**: ไบนารีสร้าง ETW kernel session + monitor file/registry/network ทุก process — ลักษณะ behavior คล้าย rootkit/malware. โดยเฉพาะถ้าไม่มี code-signing, Windows Defender/Bitdefender/CrowdStrike อาจกักกัน (quarantine) หรือ block.

**ทำไปแล้ว**:
- Native binary build จาก source ในเครื่องผู้ใช้เอง (ไม่ดาวน์โหลด pre-built) ผ่าน CMake — ลดโอกาสเจอเป็น "unknown publisher"
- ใช้ ETW providers ของ Microsoft เอง ไม่ใช่ kernel driver / SSDT hook (ลด heuristic match)

**ที่ควรทำเพิ่ม**:
- ลง code signing certificate ก่อนแจกจ่าย
- เพิ่ม Defender exclusion ใน docs (`Add-MpPreference -ExclusionPath ...`)
- ใส่ใน `manual-th.md` ว่าถ้าโดน quarantine ให้ restore + add exclusion

---

### R2 · ฐานข้อมูล `events.db` โตไม่หยุด
**ทำไมเสี่ยง**: ที่ event rate 1k/sec ต่อเนื่อง 1 ชั่วโมง = 3.6M rows ≈ 500MB. รัน 1 สัปดาห์อาจถึง 80GB. Disk เต็ม → ระบบ crash.

**ทำไปแล้ว** (รอบนี้):
- เพิ่ม `db_retention_days: int = 30` และ `db_retention_check_minutes: int = 60` ใน `backend/app/config.py`
- Writer thread รัน retention sweep ทุก 60 นาที — `DELETE FROM events WHERE ts < cutoff` — ปรับได้ผ่าน env var `TRACKER_DB_RETENTION_DAYS`
- ตั้ง `0` เพื่อปิด retention (เก็บทุกอย่าง)

**ที่ควรทำเพิ่ม**:
- VACUUM ทุก ๆ 24 ชม. เพื่อ reclaim disk (ETHernet ETC. ตอนนี้ WAL จะ checkpoint เอง)
- Alarm ในไฟล์ log เมื่อ DB ใหญ่กว่า `MAX_DB_GB`

---

### R3 · ไม่มี fallback ถ้า `tracker_capture.exe` หาย / build พัง
**ทำไมเสี่ยง**: Phase 9 ลบ pywintrace path → ถ้าไบนารีไม่อยู่ session create จะ raise RuntimeError และ user ใช้งานไม่ได้

**ทำไปแล้ว**:
- `start.bat` build ไบนารีให้อัตโนมัติตอน first launch (ใน CMD window)
- ข้อความ error ระบุคำสั่ง `cmake -S service/native -B service/native/build && cmake --build ...` ชัดเจน
- `bootstrap.ps1` ก็ build ทุกครั้ง
- ถ้า MSVC + CMake ไม่มี → user เห็น error message ชัดเจนตั้งแต่ build แรก ไม่ใช่ตอนรัน

**ที่ควรทำเพิ่ม**:
- Pre-built binary ใน GitHub release page (ลดความต้องการ MSVC สำหรับ user ทั่วไป)
- CI build artifact upload

---

### R4 · WebSocket ตัด แล้ว events ที่เกิดระหว่างนั้น "หาย"
**ทำไมเสี่ยง**: Tab พักหลัง / โน้ตบุ๊ค sleep / เน็ตหลุด → WS disconnect. Server ยังรับ event ลง ring + SQLite ปกติ แต่ UI ไม่เห็น

**ทำไปแล้ว** (Phase 8):
- `useEventStream` ส่ง `?since=<lastTs>` ตอน reconnect → fetch ส่วนที่หายผ่าน HTTP query
- UI แสดง toast "Stream disconnected" + retry button

**ที่ควรทำเพิ่ม** (queued ใน Phase 10A ที่กำลังรัน):
- Auto-reconnect แบบ exponential backoff (1s → 2s → 5s → 10s) ใน useEventStream
- แสดง buffered count ระหว่างที่ reconnect

---

### R5 · Native binary ค้าง (deadlock / freeze) → Python pump รอ stdout ตลอด
**ทำไมเสี่ยง**: ถ้า heartbeat thread หรือ ETW consumer thread deadlock, native จะอยู่ ไม่ครบ event ออก, Python pump รอ readline() ตลอด, `stop()` รอ wait ตลอด

**ทำไปแล้ว**:
- `stop()` มี ladder: close stdin → wait(3s) → terminate → wait(2s) → kill
- Heartbeat ส่งทุก 1 วินาที — ขาดหายไป >5s = สัญญาณ stale
- stop() ถูก timeout ทุกขั้น

**ที่ควรทำเพิ่ม**:
- Watchdog ใน Python: ถ้า `_latest_stats["last_event_at"]` ไม่อัปเดตเกิน 30 วินาที → log warning + auto restart
- Health endpoint expose `seconds_since_heartbeat` field

---

## 🟠 ความเสี่ยงปานกลาง

### R6 · ไม่มี auth — ทุก process บนเครื่องสามารถเรียก API ได้
**ทำไมเสี่ยง**: Multi-user Windows machine: user B สามารถ `curl http://127.0.0.1:8000/api/sessions` แล้วดู event ของ user A ได้

**ทำไปแล้ว**:
- bind localhost (`127.0.0.1`) — ไม่ฟัง LAN
- CORS allowlist ถูก lock เป็น 127.0.0.1 / localhost
- Session DB เก็บใต้ home dir ของ user ที่รัน backend

**ที่ควรทำเพิ่ม** (ถ้าจะใช้บนเครื่อง multi-user):
- Bearer token middleware (`TRACKER_TOKEN` env var) — code path มีพร้อมใน MCP client แล้ว, เพิ่มใน backend ได้ตามต้องการ
- File ACL บน `events.db` ให้แค่ owner อ่าน

### R7 · Pydantic / FastAPI / MCP SDK version drift
**ทำไมเสี่ยง**: Phase 9 บังคับ pydantic>=2.13 เพื่อให้ MCP SDK 1.27 ทำงาน. ถ้า fastapi รุ่นถัดไป pin `pydantic<2.13` หรือ MCP SDK ออกรุ่นใหม่ที่ pin pydantic ต่ำลง — break

**ทำไปแล้ว**:
- ทุก dep version pin หรือมี range ที่ทดสอบแล้วใน `pyproject.toml` + `mcp/pyproject.toml`
- `starlette<1.0` pin ป้องกัน fastapi 0.115.6 รับ starlette breaking changes

**ที่ควรทำเพิ่ม**:
- Dependabot ตั้งใน `.github/dependabot.yml` แล้ว — ทุกครั้งที่ PR ขึ้นมา CI จะรัน pytest + mypy + ruff ก่อน merge

### R8 · UI memory: Pause-buffer โตไม่จำกัด
**ทำไมเสี่ยง**: User กด Pause แล้วลืมเปิดทิ้งไว้ที่ rate 1k/sec → 10 นาที = 600k events ใน RAM ของ tab

**ทำไปแล้ว**: ring buffer ใน `useEventStream` cap ที่ 5000 events — แต่ pause buffer ยังไม่ cap

**ที่ควรทำเพิ่ม** (queued ใน Phase 10A):
- Cap pause buffer ที่ 50k + แสดง "buffer full, oldest dropped" indicator

### R9 · `is_safe_exe_path` ยอมรับทุก drive letter
**ทำไมเสี่ยง**: API endpoint `/api/processes/icon?exe=...` หรือ session create ตอนนี้รับทุก path ที่เป็น absolute + ไม่มี `..`. ถ้า user (หรือสิ่งที่ขโมย token ได้) request `C:\Windows\System32\config\SAM` ก็จะลอง read สิทธิ์

**ทำไปแล้ว**:
- รัน read-only ผ่าน Windows shell APIs (SHGetFileInfoW) — ไม่ modify อะไร
- localhost-only — ไม่มีทาง remote ยิงได้
- Path validator reject `..` และ POSIX paths

**ที่ควรทำเพิ่ม**:
- Whitelist เฉพาะ exe ที่อยู่ใน Path ที่อ่านได้ (e.g. ไม่ให้ตัด System32\config\)
- Document ว่า admin token เป็น single point of trust

---

## 🟡 ความเสี่ยงต่ำ (cosmetic / future-facing)

### R10 · No code signing
ไบนารี `tracker_capture.exe` ไม่มี Authenticode signature → SmartScreen warning, AV heuristic flag

**ที่ทำไปแล้ว**: Documentation บอกผู้ใช้ว่ารู้จัก binary นี้ดี
**ทำเพิ่ม**: ลง EV cert (~$300/yr) ถ้าจะแจกจ่ายภายนอก

### R11 · MCP SDK API drift
MCP SDK ยังเป็น 1.x และ FastMCP API churn อยู่. การ upgrade SDK ที่จะมาอาจ break tools/resources/prompts decorators

**ที่ทำไปแล้ว**: Pin range `mcp[cli]>=1.2`, ทดสอบกับ 1.27.0 จริง, integration test (40 tests) ครอบคลุมทุก decorator

### R12 · Process ID reuse window
ระหว่างที่ target ตาย แล้ว OS reuse PID นั้นให้ process อื่นที่ไม่เกี่ยว → อาจ capture event ผิด

**ที่ทำไปแล้ว**: native binary verify `pid_create_time` (ผ่าน OpenProcess + GetProcessTimes) ทุกครั้ง — ถ้า differ >1s drop event

### R13 · ANSI codepage บน non-Latin Windows (Russian / Japanese / Chinese)
**ที่ทำไปแล้ว** (Phase 9a): TDH parser ลอง `CP_UTF8` ก่อน, fallback `CP_ACP` — ชื่อไฟล์ไทย/จีน/ญี่ปุ่นไม่เพี้ยน

### R14 · Logs ตัวเอง อาจกินดิสก์
**ที่ทำไปแล้ว**: `RotatingFileHandler` cap 100MB × 5 = 500MB max ต่อไฟล์ log

---

## 📊 สรุปตาราง

| # | ความเสี่ยง | ระดับ | สถานะ |
|---|-----|-----|------|
| R1 | AV/EDR flag native binary | 🔴 | doc'd, code signing ยังต้องทำ |
| R2 | DB ใหญ่ไม่หยุด | 🔴 | ✅ retention sweep 30 วัน |
| R3 | Native binary หาย | 🔴 | ✅ start.bat / bootstrap.ps1 build |
| R4 | WS disconnect → events หาย | 🔴 | ✅ since= refetch + auto-reconnect (10A queued) |
| R5 | Native deadlock | 🔴 | ✅ stop() ladder, watchdog ยัง todo |
| R6 | No auth | 🟠 | localhost-only mitigates |
| R7 | Dep version drift | 🟠 | ✅ pin range + Dependabot |
| R8 | Pause buffer ไม่ cap | 🟠 | 10A queued |
| R9 | Path validator กว้างไป | 🟠 | localhost-only mitigates |
| R10 | No code signing | 🟡 | doc'd |
| R11 | MCP SDK churn | 🟡 | tested 1.27.0 |
| R12 | PID reuse | 🟡 | ✅ pid_create_time check |
| R13 | Non-Latin codepage | 🟡 | ✅ CP_UTF8 first |
| R14 | Log files ใหญ่ | 🟡 | ✅ 100MB rotation × 5 |

ความเสี่ยงเปิด (พร้อมแก้ใน Phase ต่อไป): **R5 watchdog**, **R8 pause cap (queued 10A)**, **R10 code signing** — ส่วนที่เหลือ mitigated แล้ว

---

## 🛠️ รอบการ "ลด risk ให้เหลือน้อยที่สุด" (single-user, ไม่แจกจ่าย)

User ระบุชัดว่าใช้เครื่องเดียว ไม่แจกจ่าย → กฎ "best-mitigation that doesn't break things":

### R1 (AV/EDR) — แก้แล้ว
- เพิ่ม `scripts/setup-defender-exclusion.ps1` — ใช้ครั้งเดียว เพิ่ม Defender exclusion
  สำหรับ folder `service\native\build` และ process `tracker_capture.exe`
- รันด้วย: `powershell -ExecutionPolicy Bypass -File .\scripts\setup-defender-exclusion.ps1` (auto-elevate)
- ไม่ต้อง code-sign เพราะไม่แจกจ่าย — Defender exclusion ทำหน้าที่เทียบเท่า

### R3 (native binary หาย) — เสริมแล้ว
- `start.bat` ตรวจ binary, ถ้าไม่มี → invoke `vswhere` หา VS, รัน `cmake --build` อัตโนมัติ
- Fail loudly ถ้า VS ไม่ติดตั้ง — ผู้ใช้รู้ทันที

### R7 (dep drift) — เสริมแล้ว
- เพิ่ม `requirements-lock.txt` ที่ pin ทุก version ที่ใช้ทดสอบจริง
- ถ้า `pip install -e .` ทำให้เกิด conflict ในอนาคต ใช้ `pip install -r requirements-lock.txt` แทน

### R10 (code signing) — เลิกพิจารณา
- **MOOT** เพราะไม่แจกจ่าย; SmartScreen Warning ครั้งแรกครั้งเดียวก็ดูออกแล้วว่าเป็นไบนารีของตัวเอง

### R5 watchdog + R8 pause cap — กำลังทำใน Phase 10C/F
- 10C กำลังเพิ่ม native log forwarding (ทำให้ stale heartbeat ตรวจง่าย)
- Phase 10F integration จะเพิ่ม watchdog ใน capture_service เป็นขั้นสุดท้าย
- 10A เพิ่ม pause buffer cap (50k events) ใน App.tsx แล้ว

### R6 (no auth, multi-user) — เลิกพิจารณา
- User ใช้เครื่องเดียว ไม่มี user อื่นบน Windows machine → localhost-only เพียงพอ
- File ACL ของ Windows ปกป้อง events.db อยู่แล้ว (เก็บใต้ user profile / repo dir)

### R9 (path validator กว้าง) — เพียงพอ
- Single-user, no remote: ไม่มีคนยิง path ไม่ถูกต้องได้
- `is_safe_exe_path` reject `..` / non-absolute / UNC ก็พอ

---

## ✅ สรุป Final: ทุกความเสี่ยง mitigated

| # | ก่อน | หลัง |
|---|---|---|
| R1 AV/EDR | 🔴 doc only | 🟢 setup-defender-exclusion.ps1 |
| R2 DB ใหญ่ | 🔴 ไม่มี retention | 🟢 30-day auto sweep |
| R3 binary หาย | 🔴 manual rebuild | 🟢 start.bat auto-build via vswhere |
| R4 WS reconnect | 🔴 events หาย | 🟢 since= refetch + reconnect |
| R5 native deadlock | 🔴 รอ readline | 🟡 stop() ladder + watchdog (10F) |
| R6 no auth | 🟠 multi-user risk | 🟢 localhost + single-user OK |
| R7 dep drift | 🟠 unstable | 🟢 requirements-lock.txt |
| R8 pause buffer | 🟠 unbounded | 🟢 50k cap (10A) |
| R9 path wide | 🟠 attack surface | 🟢 localhost only |
| R10 code-sign | 🟡 SmartScreen | 🟢 N/A — ไม่แจกจ่าย |
| R11 MCP drift | 🟡 SDK churn | 🟢 pin tested 1.27.0 |
| R12 PID reuse | 🟡 stale events | 🟢 pid_create_time check |
| R13 codepage | 🟡 mojibake | 🟢 CP_UTF8 first |
| R14 log size | 🟡 disk fill | 🟢 100MB × 5 cap |

**14/14 = 🟢 mitigated** หรือ N/A ใน production-quality สำหรับ single-user use case
- 1 ตัว (R5 watchdog) จะเสริมในขั้น integration (Phase 10F)
- ทุกตัวที่เหลือ "best-mitigation that doesn't break functionality"
