// Owns the OpenTraceW + ProcessTrace consumer thread for a real-time ETW
// session, normalizes each event, and writes one JSON line to stdout.
#pragma once

#include <windows.h>
#include <evntcons.h>
#include <evntrace.h>

#include <atomic>
#include <list>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_map>

#include "path_translator.hpp"
#include "pid_filter.hpp"

namespace tracker {

struct ConsumerConfig {
    DWORD target_pid = 0;
    ULONGLONG target_create_filetime = 0;  // 0 = no PID-reuse check
    bool engine_file = true;
    bool engine_registry = true;
    bool engine_process = true;
    bool engine_network = true;
};

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
    // no-op) and joins the worker.
    void Stop();

private:
    static void WINAPI EventCallbackThunk(PEVENT_RECORD record);
    void HandleEvent(PEVENT_RECORD record);

    void TouchFileObject(uint64_t file_object, std::wstring path);
    bool ResolveFileObject(uint64_t file_object, std::wstring& out) const;
    void ForgetFileObject(uint64_t file_object);

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
};

}  // namespace tracker
