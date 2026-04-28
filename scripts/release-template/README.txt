============================================================
 Activity Tracker — Release Build
============================================================

Real-time Windows process activity tracker. Pick a target
process and see every file / registry / process / network
event live (same visibility as Procmon, web UI).

Localhost-only, single-user. No telemetry, no cloud calls.

------------------------------------------------------------
 Quick start  /  วิธีใช้แบบเร็ว
------------------------------------------------------------

 1) Right-click  tracker.exe  →  Run as administrator
    (หรือดับเบิลคลิก  tracker.exe  แล้วกด Yes บน UAC)

 2) กดปุ่ม "Start" ในโปรแกรม
    เบราว์เซอร์จะเปิดให้อัตโนมัติ — เลือก process ที่ต้องการดู
    แล้วกด "Start capture"

 3) ปิดโปรแกรม = หยุดทุกอย่างเรียบร้อย (backend + native + ETW)

ไม่ต้องลง Python, Node.js, Visual Studio — มาพร้อมหมดแล้ว
You do NOT need to install Python / Node.js / Visual Studio.

------------------------------------------------------------
 Requirements  /  สิ่งที่ต้องมี
------------------------------------------------------------

 * Windows 10 / 11 (64-bit)
 * Administrator privileges (จำเป็นสำหรับ ETW kernel events)
 * 200 MB disk space

ทุกอย่างอื่น (Python runtime + dependencies + native binary +
web UI + MCP server) bundle มาในโฟลเดอร์นี้แล้ว — ไม่ต้องต่อเน็ต

------------------------------------------------------------
 What you get  /  ในโปรแกรม tracker.exe
------------------------------------------------------------

 * Capture monitor — สถานะ tracker_capture.exe (CPU / RAM /
   threads / handles), live sparkline events/sec, per-kind
   bar chart (file / registry / process / network)
 * Backend log — uvicorn stdout/stderr live (color-coded)
 * Per-stream logs — events / errors / native (live tail)
 * Start / Stop / Restart buttons + Open browser shortcut
 * Search box, auto-scroll toggle, save / clear / copy

------------------------------------------------------------
 Folder layout  /  โครงสร้างไฟล์
------------------------------------------------------------

 tracker.exe               GUI launcher (run as admin)
 README.txt                this file
 requirements.txt          deps list (already pre-installed in python/)
 .mcp.json                 MCP config (optional)
 python/                   bundled Python runtime + all deps
 backend/                  FastAPI control plane
 service/                  capture wrapper + native ETW binary
 ui/dist/                  pre-built web UI
 mcp/                      optional MCP server
 scripts/                  Defender exclusion helper

Files written at runtime (in this folder):
 events.db, events.db-wal, events.db-shm   captured events (SQLite)
 logs/                                      log files (rotating)
 cache/                                     icon cache

------------------------------------------------------------
 MCP server (optional)  /  ใช้กับ MCP-compatible AI client
------------------------------------------------------------

ในโปรแกรม tracker.exe มี tab "MCP How-To" บนเว็บ UI ที่บอก
วิธี config สำหรับ AI client ต่าง ๆ (Claude Code, Claude
Desktop, Cursor, Continue, Cline, ฯลฯ)

ไฟล์ .mcp.json อยู่ที่ root ของโฟลเดอร์นี้ — เปิดโฟลเดอร์นี้ใน
MCP-compatible client เพื่อใช้ activity-tracker tools ได้เลย

backend (tracker.exe) ต้องรันอยู่ก่อน MCP จึงจะเรียกได้

------------------------------------------------------------
 Troubleshooting  /  แก้ปัญหา
------------------------------------------------------------

Q: ดับเบิลคลิก tracker.exe แล้วไม่มีอะไรขึ้น
A: รอ ~2 วินาที UAC dialog จะขึ้น กด Yes

Q: Windows SmartScreen เตือน "Unknown publisher"
A: กด "More info" → "Run anyway" — โปรแกรมยังไม่ได้ code-sign
   (จะแก้ในรุ่นถัดไป) ปลอดภัยตามปกติ — open source

Q: Defender flagged tracker_capture.exe และลบทิ้ง
A: รัน  scripts\setup-defender-exclusion.ps1  แบบ admin (1 ครั้ง)
   แล้วแตก zip ใหม่ (ถ้า exe ถูกลบ)

Q: "Port 8000 in use"
A: ตั้ง  set TRACKER_PORT=8001  ก่อนเปิด tracker.exe

Q: ย้ายโฟลเดอร์ไปเครื่องอื่นได้ไหม
A: ได้ — copy ทั้งโฟลเดอร์ไป run ได้เลย ไม่ต้องลงอะไรเพิ่ม

------------------------------------------------------------
 Privacy / Security
------------------------------------------------------------

 * Listens only on 127.0.0.1 (localhost). NOT exposed to network.
 * No authentication — single-user, local-only tool.
 * No telemetry, no analytics, no cloud calls.
 * Captured events stored in events.db inside this folder.
   ลบไฟล์เพื่อล้าง history. Default retention: 30 days.

------------------------------------------------------------
 Source / Issues
------------------------------------------------------------

 https://github.com/botnick/Program-Activity-Tracker

============================================================
