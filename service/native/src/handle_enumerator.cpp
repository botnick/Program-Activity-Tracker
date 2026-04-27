#include "handle_enumerator.hpp"

#include <windows.h>
#include <winternl.h>

#include <cstddef>
#include <vector>

namespace tracker {

namespace {

// SystemExtendedHandleInformation isn't a named constant in winternl.h on
// the SDK versions we target — it's documented as 0x40 (64).
constexpr SYSTEM_INFORMATION_CLASS kSystemExtendedHandleInformation =
    static_cast<SYSTEM_INFORMATION_CLASS>(0x40);

constexpr LONG kStatusInfoLengthMismatch = static_cast<LONG>(0xC0000004);
constexpr LONG kStatusSuccess = 0;

// SYSTEM_HANDLE_TABLE_ENTRY_INFO_EX / SYSTEM_HANDLE_INFORMATION_EX are not
// exposed by winternl.h either, so define them locally. Layout matches the
// public documentation and ntddk.h.
struct SystemHandleTableEntryInfoEx {
    PVOID Object;
    ULONG_PTR UniqueProcessId;
    HANDLE HandleValue;
    ACCESS_MASK GrantedAccess;
    USHORT CreatorBackTraceIndex;
    USHORT ObjectTypeIndex;
    ULONG HandleAttributes;
    ULONG Reserved;
};

struct SystemHandleInformationEx {
    ULONG_PTR NumberOfHandles;
    ULONG_PTR Reserved;
    SystemHandleTableEntryInfoEx Handles[1];
};

using NtQuerySystemInformationFn = LONG(NTAPI*)(SYSTEM_INFORMATION_CLASS,
                                                PVOID, ULONG, PULONG);

NtQuerySystemInformationFn ResolveNtQuerySystemInformation() {
    HMODULE m = GetModuleHandleW(L"ntdll.dll");
    if (m == nullptr) {
        m = LoadLibraryW(L"ntdll.dll");
    }
    if (m == nullptr) return nullptr;
    return reinterpret_cast<NtQuerySystemInformationFn>(
        GetProcAddress(m, "NtQuerySystemInformation"));
}

}  // namespace

std::vector<OpenFileEntry> EnumerateOpenFiles(uint32_t target_pid) {
    std::vector<OpenFileEntry> out;
    if (target_pid == 0) return out;

    NtQuerySystemInformationFn nt_query = ResolveNtQuerySystemInformation();
    if (nt_query == nullptr) return out;

    // The system-wide handle table can be tens of MB; start at 256KB and
    // grow until the call stops complaining about a too-small buffer.
    std::vector<unsigned char> buf(256 * 1024);
    LONG st = kStatusInfoLengthMismatch;
    ULONG needed = 0;
    for (int retry = 0; retry < 12; ++retry) {
        st = nt_query(kSystemExtendedHandleInformation, buf.data(),
                      static_cast<ULONG>(buf.size()), &needed);
        if (st == kStatusInfoLengthMismatch) {
            // Either grow to what the kernel asked for, or double — whichever
            // is larger. Doubling guards against the table growing between
            // calls.
            size_t want = needed > buf.size() ? needed : buf.size() * 2;
            buf.resize(want);
            continue;
        }
        break;
    }
    if (st != kStatusSuccess) return out;

    auto* info = reinterpret_cast<SystemHandleInformationEx*>(buf.data());

    HANDLE target_proc =
        OpenProcess(PROCESS_DUP_HANDLE, FALSE, static_cast<DWORD>(target_pid));
    if (target_proc == nullptr) return out;

    // GetFinalPathNameByHandleW caller-supplied buffer; kernel paths can
    // exceed MAX_PATH so allow a generous 32K (matches \\?\ limit).
    constexpr DWORD kPathBufLen = 32 * 1024;
    std::vector<wchar_t> path_buf(kPathBufLen);

    for (ULONG_PTR i = 0; i < info->NumberOfHandles; ++i) {
        const auto& h = info->Handles[i];
        if (static_cast<uint32_t>(h.UniqueProcessId) != target_pid) continue;

        HANDLE dup = nullptr;
        if (!DuplicateHandle(target_proc, h.HandleValue, GetCurrentProcess(),
                             &dup, 0, FALSE, DUPLICATE_SAME_ACCESS)) {
            continue;
        }

        // Filter to real on-disk files. Pipes (FILE_TYPE_PIPE), char devices
        // (FILE_TYPE_CHAR), and unknown (FILE_TYPE_UNKNOWN) either don't have
        // a meaningful path or risk hanging GetFinalPathNameByHandleW.
        if (GetFileType(dup) != FILE_TYPE_DISK) {
            CloseHandle(dup);
            continue;
        }

        DWORD len = GetFinalPathNameByHandleW(dup, path_buf.data(), kPathBufLen,
                                              VOLUME_NAME_NT);
        if (len > 0 && len < kPathBufLen) {
            OpenFileEntry e;
            e.file_object = reinterpret_cast<uint64_t>(h.Object);
            e.nt_path.assign(path_buf.data(), len);
            out.push_back(std::move(e));
        }
        CloseHandle(dup);
    }
    CloseHandle(target_proc);
    return out;
}

}  // namespace tracker
