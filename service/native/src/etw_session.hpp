// Manages the lifecycle of a single real-time ETW session: StartTrace,
// EnableTraceEx2 for each requested provider, and ControlTrace(STOP).
#pragma once

#include <windows.h>
#include <evntrace.h>

#include <string>
#include <vector>

namespace tracker {

struct ProviderRequest {
    GUID guid;
    ULONGLONG keywords;  // 0 = enable any
    UCHAR level = TRACE_LEVEL_VERBOSE;
};

class EtwSession {
public:
    EtwSession() = default;
    ~EtwSession() { Stop(); }

    EtwSession(const EtwSession&) = delete;
    EtwSession& operator=(const EtwSession&) = delete;

    // Stop any pre-existing session with the given prefix.
    static void SweepOrphans(const std::wstring& prefix);

    // Stop a session by name (no-op if not present).
    static void StopByName(const std::wstring& session_name);

    // Allocate properties + StartTraceW. Returns 0 on success, otherwise a
    // Win32 error code.
    DWORD Start(const std::wstring& session_name);

    // EnableTraceEx2 for a single provider on the running session.
    DWORD EnableProvider(const ProviderRequest& req);

    // ControlTrace(STOP). Idempotent.
    void Stop();

    TRACEHANDLE Handle() const { return handle_; }
    const std::wstring& Name() const { return name_; }

private:
    TRACEHANDLE handle_ = 0;
    std::wstring name_;
    std::vector<uint8_t> props_buffer_;  // backing storage for EVENT_TRACE_PROPERTIES
};

}  // namespace tracker
