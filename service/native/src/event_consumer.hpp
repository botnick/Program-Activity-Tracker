// Owns the OpenTraceW + ProcessTrace consumer thread for a real-time ETW
// session, normalizes each event, and writes one JSON line to stdout.
#pragma once

#include <windows.h>
#include <evntcons.h>
#include <evntrace.h>

#include <atomic>
#include <condition_variable>
#include <cstdint>
#include <list>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

#include "handle_enumerator.hpp"
#include "path_translator.hpp"
#include "pid_filter.hpp"

namespace tracker {

// Native engine wire-format version. Bumped on any breaking change to the
// JSON schema (event lines, hello sentinel, stats sentinel). Read by the
// Python wrapper from the hello-line `version` field for handshake.
inline constexpr const char* kEngineVersion = "1.0";

struct ConsumerConfig {
    DWORD target_pid = 0;
    ULONGLONG target_create_filetime = 0;  // 0 = no PID-reuse check
    bool engine_file = true;
    bool engine_registry = true;
    bool engine_process = true;
    bool engine_network = true;
    // Heartbeat / stats sentinel cadence. 0 disables the stats thread.
    int stats_interval_ms = 1000;
};

// Serializes one JSON line (must include trailing newline OR not — caller
// chooses) to stdout under the shared stdout mutex, then fflushes. Used by
// both event-line emission and out-of-band sentinels (hello, stats) so
// nothing interleaves mid-event.
void WriteStdoutLine(const std::string& line);

// ISO 8601 UTC formatter for FILETIME ticks (100ns since 1601-01-01).
// Returns "" when filetime_ticks == 0 to denote "no event yet".
std::string FormatFiletimeIso8601(uint64_t filetime_ticks);

// ISO 8601 UTC for the current wall clock — second precision, suffixed
// with 'Z'. Used for hello / stats `ts` fields.
std::string NowIso8601Utc();

class EventConsumer {
public:
    EventConsumer(ConsumerConfig cfg, PathTranslator translator,
                  PidFilter& pids);
    ~EventConsumer();

    EventConsumer(const EventConsumer&) = delete;
    EventConsumer& operator=(const EventConsumer&) = delete;

    // Open the named real-time session and run ProcessTrace on a worker
    // thread. Returns true on success.
    bool Start(const std::wstring& session_name);

    // Closes the trace handle (if ProcessTrace already returned, this is a
    // no-op) and joins the worker (and the stats thread, if started).
    void Stop();

    // Pre-populate the FileObject->path cache from currently-open handles
    // (typically obtained via tracker::EnumerateOpenFiles before tracing
    // starts). Best-effort: each entry's NT path is run through the same
    // PathTranslator used by ETW events, and entries already present in the
    // cache are skipped so we don't clobber fresher data.
    void SeedFileObjectCache(const std::vector<OpenFileEntry>& entries);

    // Counters surfaced to the heartbeat / stats sentinel.
    uint64_t Errors() const { return errors_.load(std::memory_order_relaxed); }
    uint64_t LastEventFiletime() const {
        return last_event_filetime_.load(std::memory_order_relaxed);
    }
    size_t FileCacheSize() const;
    size_t KeyCacheSize() const;

private:
    static void WINAPI EventCallbackThunk(PEVENT_RECORD record);
    void HandleEvent(PEVENT_RECORD record);

    void TouchFileObject(uint64_t file_object, std::wstring path);
    bool ResolveFileObject(uint64_t file_object, std::wstring& out) const;
    void ForgetFileObject(uint64_t file_object);

    // KeyObject cache — the registry counterpart to the FileObject cache.
    // Most ETW Microsoft-Windows-Kernel-Registry events carry a KeyObject
    // (KCB) pointer plus the KeyName ONLY on kcb_create / open_key /
    // create_key. Subsequent set_value / delete_value / kcb_rundown_end /
    // kcb_delete events give us only the pointer, so we keep a bounded
    // map and resolve at emit time. Same LRU + cap shape as the file cache.
    void TouchKeyObject(uint64_t key_object, std::wstring name);
    bool ResolveKeyObject(uint64_t key_object, std::wstring& out) const;
    void ForgetKeyObject(uint64_t key_object);

    void StatsLoop();
    void EmitStatsSentinel();

    static thread_local EventConsumer* current_;

    ConsumerConfig cfg_;
    PathTranslator translator_;
    PidFilter& pids_;

    TRACEHANDLE trace_handle_ = INVALID_PROCESSTRACE_HANDLE;
    std::thread worker_;
    std::atomic<bool> running_{false};

    mutable std::mutex file_cache_mu_;
    std::unordered_map<uint64_t, std::wstring> file_paths_;
    std::list<uint64_t> file_lru_;  // front = MRU
    std::unordered_map<uint64_t, std::list<uint64_t>::iterator> file_lru_pos_;
    static constexpr size_t kFileCacheCap = 100'000;

    mutable std::mutex key_cache_mu_;
    std::unordered_map<uint64_t, std::wstring> key_paths_;
    std::list<uint64_t> key_lru_;  // front = MRU
    std::unordered_map<uint64_t, std::list<uint64_t>::iterator> key_lru_pos_;
    static constexpr size_t kKeyCacheCap = 100'000;

    // Heartbeat / stats thread. Woken via stats_cv_ on shutdown so we don't
    // block up to stats_interval_ms during clean stop.
    std::thread stats_worker_;
    std::mutex stats_mu_;
    std::condition_variable stats_cv_;
    bool stats_stop_ = false;

    std::atomic<uint64_t> errors_{0};
    std::atomic<uint64_t> last_event_filetime_{0};
};

}  // namespace tracker
