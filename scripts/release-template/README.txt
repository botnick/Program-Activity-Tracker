============================================================
 Activity Tracker - Release Build
============================================================

Real-time Windows process activity tracker. Pick a target
process and see every file / registry / process / network
event live (same visibility as Procmon, web UI).

Localhost-only, single-user. No telemetry. No cloud calls.

------------------------------------------------------------
 Quick start  /  วิธีใช้แบบเร็ว
------------------------------------------------------------

1) Install Python 3.10+
   ติดตั้ง Python 3.10 ขึ้นไป
   https://www.python.org/downloads/
   *** ตอนติดตั้งให้ติ๊ก "Add Python to PATH" ด้วย ***

2) Double-click  start.bat
   ดับเบิลคลิก start.bat
   - Windows จะถาม UAC (administrator) -> กด Yes
   - ครั้งแรกจะติดตั้ง dependencies ~30 MB (ใช้เวลา 1-2 นาที)
   - เบราว์เซอร์จะเปิด http://127.0.0.1:8000 อัตโนมัติ

3) Pick a process and click "Start capture"
   เลือก process ที่ต้องการดู แล้วกด "Start capture"

4) To stop: close the cmd window OR double-click stop.bat
   ปิดหน้า cmd หรือดับเบิลคลิก stop.bat เพื่อหยุด

------------------------------------------------------------
 Requirements  /  สิ่งที่ต้องมี
------------------------------------------------------------

 * Windows 10 / 11 (64-bit)
 * Python 3.10 or newer, on PATH
 * Administrator privileges (จำเป็นสำหรับ ETW kernel events)
 * Internet (ครั้งแรกเท่านั้น เพื่อติดตั้ง pip dependencies)

You do NOT need: Visual Studio, CMake, Node.js, npm.
ไม่ต้องลง: Visual Studio, CMake, Node.js, npm

------------------------------------------------------------
 Folder layout  /  โครงสร้างไฟล์
------------------------------------------------------------

 start.bat                 launcher (auto-elevates to admin)
 stop.bat                  kills backend + native binary + ETW sessions
 README.txt                this file
 requirements.txt          Python runtime dependencies
 .mcp.json                 MCP client config (optional)
 backend/                  FastAPI control plane (Python source)
 service/                  capture wrapper + native ETW binary
 ui/dist/                  pre-built web UI (HTML/JS/CSS)
 mcp/                      optional MCP server (stdio, talks to backend HTTP)
 scripts/                  Defender exclusion helper (optional)

------------------------------------------------------------
 MCP server (optional)  /  ใช้กับ MCP-compatible client
------------------------------------------------------------

start.bat ติดตั้ง mcp_tracker ให้อัตโนมัติ (ถ้ามีโฟลเดอร์ mcp/)
ไฟล์ .mcp.json อยู่ที่ root ของโฟลเดอร์นี้แล้ว — เปิดโฟลเดอร์นี้ใน
MCP-compatible client (เช่น Claude Code) แล้วจะเห็น 14 tools ของ
activity-tracker พร้อมใช้

ถ้าจะใช้กับ MCP client ตัวอื่น ๆ ให้กำหนด config:
    "command": "python"
    "args":    ["-m", "mcp_tracker"]
    "env":     {"MCP_TRACKER_URL": "http://127.0.0.1:8000"}

backend (start.bat) ต้องรันอยู่ก่อน MCP จึงจะเรียกได้

Files written at runtime (in this folder):
 events.db, events.db-wal, events.db-shm   captured events (SQLite)
 logs/                                      log files
 cache/                                     icon cache

------------------------------------------------------------
 Troubleshooting  /  แก้ปัญหา
------------------------------------------------------------

Q: "[ERROR] Python 3.10+ not found"
A: Install Python from python.org and tick "Add Python to PATH".
   Then re-run start.bat.

Q: "[ERROR] Port 8000 is already in use"
A: Run stop.bat first. Or set TRACKER_PORT=8001 before start.bat.

Q: Windows Defender flagged tracker_capture.exe and quarantined it
A: Run the exclusion helper as admin (one-time):
      powershell -ExecutionPolicy Bypass -File scripts\setup-defender-exclusion.ps1
   Then re-extract the zip if the exe was deleted.

Q: WebSocket disconnects, events stop arriving
A: Make sure no proxy/VPN intercepts localhost traffic.

Q: "tracker_capture.exe missing" or "ui/dist/index.html missing"
A: The release zip is incomplete. Re-extract it preserving the folder
   structure (some unzip tools strip the top-level folder).

Q: Can I move this folder to another machine?
A: Yes - copy the whole folder. First run on the new machine will
   pip-install dependencies again.

------------------------------------------------------------
 Privacy  /  ความเป็นส่วนตัว
------------------------------------------------------------

 * Listens only on 127.0.0.1 (localhost). NOT exposed to the network.
 * No authentication - this is a single-user, local-only tool.
 * No telemetry, no analytics, no cloud calls. Everything is local.
 * Captured events are stored in events.db (SQLite) inside this folder.
   Delete the file to wipe history. Default retention: 30 days.

------------------------------------------------------------
 License / Source
------------------------------------------------------------

This is a release build. The full source repository, including
the C++ ETW capture engine and the React UI source, is available
to developers separately.

============================================================
