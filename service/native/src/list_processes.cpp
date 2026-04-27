// Implementation of EnumerateProcesses() — see list_processes.hpp.
//
// Strategy:
//   1. CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS) for pid/ppid/basename.
//   2. For each pid: OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION) and
//      QueryFullProcessImageNameW for the full exe path.
//   3. OpenProcessToken(TOKEN_QUERY) + GetTokenInformation(TokenUser) +
//      LookupAccountSidW for the owning principal.
//
// Each step is best-effort; failure leaves the corresponding field empty
// instead of dropping the row. Handles are always closed on every path.
#include "list_processes.hpp"

#include <windows.h>
#include <tlhelp32.h>
#include <psapi.h>

#include <string>
#include <vector>

namespace tracker {
namespace {

std::wstring GetProcessExePath(DWORD pid) {
    HANDLE h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
    if (h == nullptr) return std::wstring();
    wchar_t buf[MAX_PATH * 2] = {0};
    DWORD len = static_cast<DWORD>(sizeof(buf) / sizeof(buf[0]));
    std::wstring out;
    if (QueryFullProcessImageNameW(h, 0, buf, &len)) {
        out.assign(buf, len);
    }
    CloseHandle(h);
    return out;
}

std::wstring GetProcessUserName(DWORD pid) {
    HANDLE proc = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
    if (proc == nullptr) return std::wstring();

    HANDLE tok = nullptr;
    if (!OpenProcessToken(proc, TOKEN_QUERY, &tok)) {
        CloseHandle(proc);
        return std::wstring();
    }

    DWORD needed = 0;
    GetTokenInformation(tok, TokenUser, nullptr, 0, &needed);
    if (needed == 0 || GetLastError() != ERROR_INSUFFICIENT_BUFFER) {
        CloseHandle(tok);
        CloseHandle(proc);
        return std::wstring();
    }

    std::vector<BYTE> buf(needed);
    if (!GetTokenInformation(tok, TokenUser, buf.data(), needed, &needed)) {
        CloseHandle(tok);
        CloseHandle(proc);
        return std::wstring();
    }

    auto* tu = reinterpret_cast<TOKEN_USER*>(buf.data());
    wchar_t name[256] = {0};
    wchar_t domain[256] = {0};
    DWORD n_len = 256;
    DWORD d_len = 256;
    SID_NAME_USE sid_type = SidTypeUnknown;
    BOOL ok = LookupAccountSidW(nullptr, tu->User.Sid,
                                name, &n_len,
                                domain, &d_len, &sid_type);
    CloseHandle(tok);
    CloseHandle(proc);
    if (!ok) return std::wstring();

    std::wstring out;
    out.reserve(d_len + 1 + n_len);
    out.append(domain);
    out.push_back(L'\\');
    out.append(name);
    return out;
}

}  // namespace

std::vector<ProcessInfo> EnumerateProcesses() {
    std::vector<ProcessInfo> out;
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snap == INVALID_HANDLE_VALUE) {
        return out;
    }

    PROCESSENTRY32W pe;
    ZeroMemory(&pe, sizeof(pe));
    pe.dwSize = sizeof(pe);

    if (!Process32FirstW(snap, &pe)) {
        CloseHandle(snap);
        return out;
    }

    do {
        ProcessInfo pi;
        pi.pid = pe.th32ProcessID;
        pi.ppid = pe.th32ParentProcessID;
        pi.name = pe.szExeFile;  // basename only, NUL-terminated
        if (pi.pid != 0) {
            pi.exe = GetProcessExePath(pi.pid);
            pi.username = GetProcessUserName(pi.pid);
        }
        out.push_back(std::move(pi));
    } while (Process32NextW(snap, &pe));

    CloseHandle(snap);
    return out;
}

}  // namespace tracker
