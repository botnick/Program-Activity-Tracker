// Lightweight process snapshot used by `tracker_capture --list-processes`.
//
// EnumerateProcesses() runs CreateToolhelp32Snapshot + Process32{First,Next}W
// for the basic pid/ppid/name fields, then attempts to enrich each entry
// with the full executable path and owning user via OpenProcess /
// QueryFullProcessImageNameW / OpenProcessToken / LookupAccountSidW.
//
// Per-process enrichment failures (typically ACCESS_DENIED on PID 0/4 or
// other-session processes when not running elevated) are swallowed: the
// entry is still returned with empty `exe` / `username`, so callers see
// "no access" rather than a missing row.
#pragma once

#include <windows.h>

#include <string>
#include <vector>

namespace tracker {

struct ProcessInfo {
    DWORD pid = 0;
    DWORD ppid = 0;
    std::wstring name;       // basename, e.g. "explorer.exe"
    std::wstring exe;        // full path; empty if access denied
    std::wstring username;   // "DOMAIN\\user"; empty if access denied
};

// Snapshot all running processes. Errors during per-process attribute fetch
// are swallowed -- the process is still included with empty exe / username
// fields. Returns an empty vector only if the Toolhelp snapshot itself fails.
std::vector<ProcessInfo> EnumerateProcesses();

}  // namespace tracker
