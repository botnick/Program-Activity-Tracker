# Risk Register — Activity Tracker

เอกสารสรุปความเสี่ยงหลักของระบบและสิ่งที่ทำไปแล้วเพื่อลดความเสี่ยง
อิงสภาพ repo ปัจจุบัน (post Phase 10) ซึ่ง **single-user, ไม่แจกจ่าย**

---

## ✅ ตารางสรุป

| # | ความเสี่ยง | ระดับ | สถานะ | วิธีแก้ |
|---|---|---|---|---|
| R1 | AV/EDR flag `tracker_capture.exe` | 🔴 | 🟢 mitigated | `scripts/setup-defender-exclusion.ps1` (one-time) |
| R2 | `events.db` โตไม่หยุด | 🔴 | 🟢 mitigated | retention sweep 30 วัน ใน writer thread |
| R3 | Native binary ไม่มี / build พัง | 🔴 | 🟢 mitigated | `start.bat` auto-build ผ่าน vswhere + cmake |
| R4 | WS disconnect → events หาย | 🔴 | 🟢 mitigated | `since=` refetch ตอน reconnect |
| R5 | Native binary deadlock / freeze | 🔴 | 🟡 partial | `stop()` ladder (close stdin → terminate → kill) — watchdog ยังไม่ได้ทำ |
| R6 | No auth (multi-user machine) | 🟠 | 🟢 N/A | localhost-only + single-user assumption |
| R7 | Dependency version drift | 🟠 | 🟢 mitigated | `requirements-lock.txt` + Dependabot CI |
| R8 | Pause buffer / live ring โต | 🟠 | 🟢 mitigated | cap 5000 events ที่ฝั่ง client (rAF batched) |
| R9 | Path validator กว้างไป | 🟠 | 🟢 N/A | localhost-only — ไม่มีคน remote ยิง |
| R10 | No code signing | 🟡 | 🟢 N/A | ไม่แจกจ่าย → SmartScreen warning ไม่เกี่ยว |
| R11 | MCP SDK API drift | 🟡 | 🟢 mitigated | pin `mcp[cli]>=1.2`, tested 1.27.0 |
| R12 | PID reuse leak | 🟡 | 🟢 mitigated | native ตรวจ `pid_create_time` ทุก event |
| R13 | Non-Latin codepage mojibake | 🟡 | 🟢 mitigated | TDH ลอง `CP_UTF8` ก่อน, fallback `CP_ACP` |
| R14 | Log file ใหญ่ | 🟡 | 🟢 mitigated | `RotatingFileHandler` cap (50–100 MB × 3–5) |

**14/14 mitigated หรือ N/A** — ยกเว้น R5 watchdog ที่ยัง partial (มี timeout-ladder อยู่แล้ว แต่ไม่มี auto-restart)

---

## รายละเอียดเชิงลึก

### R1 · AV/EDR flag
ETW kernel binary ที่ไม่ได้ sign อาจถูก Defender quarantine
**แก้**: `powershell -ExecutionPolicy Bypass -File .\scripts\setup-defender-exclusion.ps1`
สคริปต์ขอ UAC แล้ว `Add-MpPreference -ExclusionPath service\native\build` + `-ExclusionProcess tracker_capture.exe`

### R2 · DB ใหญ่ไม่หยุด
ที่ rate 1k events/sec × 1 ชั่วโมง = ~500 MB. รัน 1 สัปดาห์อาจ 80 GB
**แก้**: writer thread รัน `DELETE FROM events WHERE ts < cutoff` ทุก 60 นาที
ปรับได้: `TRACKER_DB_RETENTION_DAYS=N` (`0` = ปิด retention)

### R3 · Native binary หาย
Phase 9 ลบ pywintrace fallback → ถ้า binary ไม่มี start_session จะ raise
**แก้**: `start.bat` ใช้ `vswhere.exe` หา VS แล้วรัน `cmake --build` ให้อัตโนมัติ
ถ้า VS ไม่ติดตั้ง → error message ระบุชัดเจน

### R4 · WS disconnect → events หาย
**แก้**: `useEventStream` track `lastTsRef`; ตอน WS reconnect ส่ง `?since=<ts>`
ผ่าน HTTP fetch — ดึง events ที่เกิดระหว่างนั้นมาเติม

### R5 · Native deadlock (partial)
**ทำแล้ว**: `stop()` ladder — close stdin (3s) → terminate (2s) → kill
**ยังไม่ได้ทำ**: watchdog ที่ตรวจ `last_heartbeat_at` ว่าเก่ากว่า 30s แล้ว auto-restart
**ทำไมไม่ทำตอนนี้**: heartbeat 1Hz มีอยู่แล้ว (native ส่ง `{"type":"stats"}` ทุก 1 วินาที)
ถ้าจะทำ watchdog เพิ่มก็ทำได้ แต่ไม่ใช่ blocker สำหรับ single-user use

### R6 · No auth (N/A)
**ทำไม N/A**: เครื่องเดียว user เดียว — ไม่ต้องการ shared secret
ถ้าจะ expose LAN: ดู `docs/threat-model.md` ส่วน "If you ever expose this"

### R7 · Dep drift
**ทำไม mitigate**: `requirements-lock.txt` pin ทุก version ที่ผ่าน test
`.github/workflows/ci.yml` รัน pytest + ruff + mypy ก่อน merge ทุก PR

### R8 · Pause buffer
**ทำไม mitigate**: ring buffer ฝั่ง UI cap 5000 events; client-side pause buffer
ก็ทำงานบน ring เดียวกัน — ไม่โตไม่จำกัด. rAF batching ป้องกัน UI กระตุก

### R12 · PID reuse
ระหว่างที่ target ตาย แล้ว OS reuse PID ให้ process อื่น
**ทำไม mitigate**: native binary capture `GetProcessTimes(target_pid)` ตอน start
แล้ว verify ทุก event — ถ้า create_time ต่างเกิน 1s drop event

### R13 · Non-Latin codepage
Windows ANSI codepage บนระบบรัสเซีย/ญี่ปุ่น/จีน อาจทำชื่อไฟล์เพี้ยน
**ทำไม mitigate**: `tdh_parser.cpp` ลอง `MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, ...)` ก่อน
fallback `CP_ACP` เฉพาะ `ERROR_NO_UNICODE_TRANSLATION`

---

## สรุป

**Production-ready** สำหรับ single-user use case. ความเสี่ยง 13/14 ตัวมี mitigation แล้ว
R5 watchdog เป็น nice-to-have ที่จะเสริมได้เมื่อจำเป็น แต่ไม่ block การใช้งานปัจจุบัน
