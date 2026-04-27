#include "etw_session.hpp"

#include <windows.h>
#include <evntrace.h>
#include <evntcons.h>

#include <cstring>

namespace tracker {

namespace {

constexpr size_t kPropertiesSize =
    sizeof(EVENT_TRACE_PROPERTIES) + (1024 * sizeof(wchar_t)) +
    (1024 * sizeof(wchar_t));

// Build a properties buffer suitable for StartTraceW / ControlTraceW. The
// caller-supplied vector is resized; returns the typed pointer.
EVENT_TRACE_PROPERTIES* BuildProperties(std::vector<uint8_t>& storage,
                                        const std::wstring& session_name) {
    storage.assign(kPropertiesSize, 0);
    auto* props = reinterpret_cast<EVENT_TRACE_PROPERTIES*>(storage.data());
    props->Wnode.BufferSize = static_cast<ULONG>(kPropertiesSize);
    props->Wnode.Flags = WNODE_FLAG_TRACED_GUID;
    props->Wnode.ClientContext = 1;  // QueryPerformanceCounter
    props->LogFileMode = EVENT_TRACE_REAL_TIME_MODE | EVENT_TRACE_NO_PER_PROCESSOR_BUFFERING;
    props->LoggerNameOffset = sizeof(EVENT_TRACE_PROPERTIES);
    props->LogFileNameOffset = sizeof(EVENT_TRACE_PROPERTIES) +
                                1024 * sizeof(wchar_t);
    auto* logger_name = reinterpret_cast<wchar_t*>(storage.data() +
                                                    props->LoggerNameOffset);
    size_t copy_chars = std::min<size_t>(session_name.size(), 1023);
    std::memcpy(logger_name, session_name.data(),
                copy_chars * sizeof(wchar_t));
    logger_name[copy_chars] = L'\0';
    return props;
}

}  // namespace

void EtwSession::StopByName(const std::wstring& session_name) {
    std::vector<uint8_t> storage;
    auto* props = BuildProperties(storage, session_name);
    ControlTraceW(0, session_name.c_str(), props, EVENT_TRACE_CONTROL_STOP);
}

void EtwSession::SweepOrphans(const std::wstring& prefix) {
    // Query all running sessions via QueryAllTracesW and stop those that
    // start with the prefix.
    constexpr ULONG kMaxSessions = 64;
    std::vector<std::vector<uint8_t>> bufs(kMaxSessions);
    std::vector<EVENT_TRACE_PROPERTIES*> ptrs(kMaxSessions, nullptr);
    for (ULONG i = 0; i < kMaxSessions; ++i) {
        bufs[i].assign(kPropertiesSize, 0);
        auto* p = reinterpret_cast<EVENT_TRACE_PROPERTIES*>(bufs[i].data());
        p->Wnode.BufferSize = static_cast<ULONG>(kPropertiesSize);
        p->LoggerNameOffset = sizeof(EVENT_TRACE_PROPERTIES);
        p->LogFileNameOffset =
            sizeof(EVENT_TRACE_PROPERTIES) + 1024 * sizeof(wchar_t);
        ptrs[i] = p;
    }
    ULONG returned = 0;
    ULONG status = QueryAllTracesW(ptrs.data(), kMaxSessions, &returned);
    if (status != ERROR_SUCCESS) {
        return;
    }
    for (ULONG i = 0; i < returned; ++i) {
        const wchar_t* name = reinterpret_cast<const wchar_t*>(
            reinterpret_cast<PBYTE>(ptrs[i]) + ptrs[i]->LoggerNameOffset);
        std::wstring n(name);
        if (n.size() >= prefix.size() &&
            n.compare(0, prefix.size(), prefix) == 0) {
            StopByName(n);
        }
    }
}

DWORD EtwSession::Start(const std::wstring& session_name) {
    name_ = session_name;
    auto* props = BuildProperties(props_buffer_, session_name);
    // Reasonable defaults for a real-time session.
    props->BufferSize = 64;        // KB per buffer
    props->MinimumBuffers = 16;
    props->MaximumBuffers = 64;
    props->FlushTimer = 1;         // seconds

    ULONG status = StartTraceW(&handle_, session_name.c_str(), props);
    if (status == ERROR_ALREADY_EXISTS) {
        // Best-effort cleanup, then retry once.
        StopByName(session_name);
        props = BuildProperties(props_buffer_, session_name);
        props->BufferSize = 64;
        props->MinimumBuffers = 16;
        props->MaximumBuffers = 64;
        props->FlushTimer = 1;
        status = StartTraceW(&handle_, session_name.c_str(), props);
    }
    if (status != ERROR_SUCCESS) {
        handle_ = 0;
    }
    return status;
}

DWORD EtwSession::EnableProvider(const ProviderRequest& req) {
    if (handle_ == 0) return ERROR_INVALID_STATE;
    ENABLE_TRACE_PARAMETERS params{};
    params.Version = ENABLE_TRACE_PARAMETERS_VERSION_2;
    params.EnableProperty = 0;
    params.SourceId = req.guid;

    return EnableTraceEx2(handle_, &req.guid, EVENT_CONTROL_CODE_ENABLE_PROVIDER,
                          req.level,
                          /*MatchAnyKeyword=*/req.keywords,
                          /*MatchAllKeyword=*/0,
                          /*Timeout=*/0, &params);
}

void EtwSession::Stop() {
    if (handle_ == 0) return;
    auto* props = reinterpret_cast<EVENT_TRACE_PROPERTIES*>(props_buffer_.data());
    ControlTraceW(handle_, name_.c_str(), props, EVENT_TRACE_CONTROL_STOP);
    handle_ = 0;
}

}  // namespace tracker
