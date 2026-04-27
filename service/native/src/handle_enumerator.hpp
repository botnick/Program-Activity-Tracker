// Best-effort enumeration of file handles already open in a target process.
//
// At session start we cannot observe the kernel CreateFile that opened
// pre-existing handles, so the ETW FileObject->path cache has no entry for
// them. Enumerating now gives us (FILE_OBJECT*, NT path) pairs we can pre-
// seed into the cache so subsequent Read/Write/Close events resolve to a
// real path instead of "[handle 0x...]".
#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace tracker {

struct OpenFileEntry {
    uint64_t file_object;   // PVOID Object — matches ETW FileObject
    std::wstring nt_path;   // raw NT-form path; caller translates if needed
};

// Returns the list of open file handles owned by `target_pid` along with the
// FILE_OBJECT pointer (the same value ETW emits as `FileObject`). Errors are
// swallowed: a partial list is fine, an empty list is fine, the function
// never throws or aborts.
std::vector<OpenFileEntry> EnumerateOpenFiles(uint32_t target_pid);

}  // namespace tracker
