#include "event_consumer.hpp"

// Winsock must precede windows.h to keep ws2ipdef from blowing up.
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <evntcons.h>
#include <evntrace.h>
#include <rpc.h>

#include <chrono>
#include <cstdio>
#include <cstring>
#include <iomanip>
#include <mutex>
#include <sstream>
#include <string>

#include "json_writer.hpp"
#include "provider_guids.hpp"
#include "tdh_parser.hpp"

namespace tracker {

thread_local EventConsumer* EventConsumer::current_ = nullptr;

namespace {

std::mutex& StdoutMutex() {
    static std::mutex m;
    return m;
}

// Format a FILETIME (100ns ticks since 1601-01-01) as ISO 8601 UTC with
// microsecond precision.
std::string FormatTimestamp(ULONGLONG filetime_ticks) {
    if (filetime_ticks == 0) {
        SYSTEMTIME now{};
        GetSystemTime(&now);
        FILETIME ft{};
        SystemTimeToFileTime(&now, &ft);
        ULARGE_INTEGER u;
        u.LowPart = ft.dwLowDateTime;
        u.HighPart = ft.dwHighDateTime;
        filetime_ticks = u.QuadPart;
    }
    FILETIME ft;
    ULARGE_INTEGER u;
    u.QuadPart = filetime_ticks;
    ft.dwLowDateTime = u.LowPart;
    ft.dwHighDateTime = u.HighPart;
    SYSTEMTIME st{};
    if (!FileTimeToSystemTime(&ft, &st)) {
        return "1970-01-01T00:00:00Z";
    }
    // Microseconds = (ticks % 10_000_000) / 10
    ULONGLONG sub = filetime_ticks % 10'000'000ULL;
    unsigned micros = static_cast<unsigned>(sub / 10ULL);
    char buf[64];
    int n = std::snprintf(buf, sizeof(buf),
                          "%04u-%02u-%02uT%02u:%02u:%02u.%06u+00:00",
                          st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute,
                          st.wSecond, micros);
    if (n <= 0) return "1970-01-01T00:00:00Z";
    return std::string(buf, static_cast<size_t>(n));
}

// Generate a UUID v4-ish string. We use UuidCreate + UuidToString.
std::string MakeUuid() {
    UUID u{};
    UuidCreate(&u);
    RPC_CSTR str = nullptr;
    if (UuidToStringA(&u, &str) != RPC_S_OK || str == nullptr) {
        return "00000000-0000-0000-0000-000000000000";
    }
    std::string out(reinterpret_cast<const char*>(str));
    RpcStringFreeA(&str);
    return out;
}

// Promote relevant decoded properties into a `details` JsonObject. Skips
// keys listed in `drop`.
JsonObject DecodeDetails(const DecodedEvent& ev,
                         std::initializer_list<const wchar_t*> drop) {
    JsonObject details;
    for (const auto& [k, v] : ev.props) {
        bool skip = false;
        for (const wchar_t* d : drop) {
            if (k == d) {
                skip = true;
                break;
            }
        }
        if (skip) continue;
        std::string key_utf8 = WideToUtf8(k);
        if (auto* s = std::get_if<std::wstring>(&v)) {
            details.emplace_back(std::move(key_utf8), WStr(*s));
        } else if (auto* i = std::get_if<long long>(&v)) {
            details.emplace_back(std::move(key_utf8), JsonValue(*i));
        } else if (auto* u = std::get_if<unsigned long long>(&v)) {
            details.emplace_back(std::move(key_utf8), JsonValue(*u));
        } else {
            details.emplace_back(std::move(key_utf8), JsonValue());
        }
    }
    return details;
}

// Format an IPv4 address from a 32-bit network/host integer. ETW kernel-
// network events typically carry these in network byte order.
std::string FormatIpv4(unsigned long long raw) {
    in_addr a{};
    a.S_un.S_addr = static_cast<ULONG>(raw & 0xFFFFFFFFULL);
    char buf[INET_ADDRSTRLEN] = {0};
    inet_ntop(AF_INET, &a, buf, sizeof(buf));
    return buf;
}

const wchar_t* OperationLabel(const wchar_t* kind, USHORT event_id) {
    auto find_in = [&](const std::unordered_map<unsigned, const wchar_t*>& m)
        -> const wchar_t* {
        auto it = m.find(static_cast<unsigned>(event_id));
        return it != m.end() ? it->second : nullptr;
    };
    if (std::wstring(kind) == L"file") return find_in(FileEvents());
    if (std::wstring(kind) == L"registry") return find_in(RegistryEvents());
    if (std::wstring(kind) == L"process") return find_in(ProcessEvents());
    if (std::wstring(kind) == L"network") return find_in(NetworkEvents());
    return nullptr;
}

}  // namespace

EventConsumer::EventConsumer(ConsumerConfig cfg, PathTranslator translator,
                             PidFilter& pids)
    : cfg_(std::move(cfg)),
      translator_(std::move(translator)),
      pids_(pids) {}

EventConsumer::~EventConsumer() { Stop(); }

bool EventConsumer::Start(const std::wstring& session_name) {
    EVENT_TRACE_LOGFILEW logfile{};
    logfile.LoggerName = const_cast<LPWSTR>(session_name.c_str());
    logfile.ProcessTraceMode = PROCESS_TRACE_MODE_REAL_TIME |
                               PROCESS_TRACE_MODE_EVENT_RECORD;
    logfile.EventRecordCallback = &EventConsumer::EventCallbackThunk;
    logfile.Context = this;

    trace_handle_ = OpenTraceW(&logfile);
    if (trace_handle_ == INVALID_PROCESSTRACE_HANDLE) {
        return false;
    }

    running_ = true;
    worker_ = std::thread([this]() {
        current_ = this;
        ProcessTrace(&trace_handle_, 1, nullptr, nullptr);
        current_ = nullptr;
    });
    return true;
}

void EventConsumer::Stop() {
    if (!running_.exchange(false)) return;
    if (trace_handle_ != INVALID_PROCESSTRACE_HANDLE) {
        CloseTrace(trace_handle_);
        trace_handle_ = INVALID_PROCESSTRACE_HANDLE;
    }
    if (worker_.joinable()) worker_.join();
}

void WINAPI EventConsumer::EventCallbackThunk(PEVENT_RECORD record) {
    auto* self = static_cast<EventConsumer*>(record->UserContext);
    if (self) self->HandleEvent(record);
}

void EventConsumer::HandleEvent(PEVENT_RECORD record) {
    const wchar_t* kind = ProviderKind(record->EventHeader.ProviderId);
    if (kind == nullptr) return;

    DecodedEvent ev;
    if (!DecodeEvent(record, ev)) {
        return;
    }

    const std::wstring kind_w(kind);

    // For process events, payload-ProcessID may be different from the header
    // ProcessId (the system process emits the start record).
    DWORD relevant_pid = ev.process_id;
    if (kind_w == L"process") {
        unsigned long long payload_pid = 0;
        if (GetUInt(ev, L"ProcessID", payload_pid) ||
            GetUInt(ev, L"ProcessId", payload_pid)) {
            relevant_pid = static_cast<DWORD>(payload_pid);
        }
        // Maintain the descendant set on start.
        if (ev.event_id == 1) {
            unsigned long long parent_pid = 0;
            if (GetUInt(ev, L"ParentProcessID", parent_pid) ||
                GetUInt(ev, L"ParentProcessId", parent_pid)) {
                pids_.AddIfParentTracked(static_cast<DWORD>(parent_pid),
                                         static_cast<DWORD>(payload_pid));
            }
        } else if (ev.event_id == 2) {
            pids_.Remove(relevant_pid);
        }
    }

    if (!pids_.Contains(relevant_pid)) {
        return;
    }

    if (cfg_.target_create_filetime != 0 &&
        relevant_pid == cfg_.target_pid) {
        if (!pids_.VerifyCreateTime(cfg_.target_pid,
                                    cfg_.target_create_filetime)) {
            return;
        }
    }

    // Engine gating.
    if (kind_w == L"file" && !cfg_.engine_file) return;
    if (kind_w == L"registry" && !cfg_.engine_registry) return;
    if (kind_w == L"process" && !cfg_.engine_process) return;
    if (kind_w == L"network" && !cfg_.engine_network) return;

    // File-object cache maintenance.
    if (kind_w == L"file") {
        unsigned long long file_object = 0;
        if (!GetUInt(ev, L"FileObject", file_object)) {
            GetUInt(ev, L"FileKey", file_object);
        }
        const std::wstring* fname = GetString(ev, L"FileName");
        if (!fname) fname = GetString(ev, L"OpenPath");
        if (!fname) fname = GetString(ev, L"FilePath");

        if (ev.event_id == 12 && file_object != 0 && fname != nullptr &&
            !fname->empty()) {
            TouchFileObject(file_object, translator_.Translate(*fname));
        }
        if (ev.event_id == 14 && file_object != 0) {
            ForgetFileObject(file_object);
        }
    }

    // Build the JSON payload.
    JsonObject root;
    root.emplace_back("id", JsonValue(MakeUuid()));
    root.emplace_back("ts", JsonValue(FormatTimestamp(ev.timestamp_ft)));
    root.emplace_back("kind", JsonValue(WideToUtf8(kind_w)));
    const wchar_t* op = OperationLabel(kind, ev.event_id);
    if (op) {
        root.emplace_back("operation", JsonValue(WideToUtf8(op)));
    } else {
        char buf[32];
        std::snprintf(buf, sizeof(buf), "event_%u",
                      static_cast<unsigned>(ev.event_id));
        root.emplace_back("operation", JsonValue(std::string(buf)));
    }
    root.emplace_back("pid", JsonValue(static_cast<long long>(relevant_pid)));

    if (kind_w == L"file") {
        std::wstring path;
        const std::wstring* fname = GetString(ev, L"FileName");
        if (!fname) fname = GetString(ev, L"OpenPath");
        if (!fname) fname = GetString(ev, L"FilePath");
        if (fname && !fname->empty()) {
            path = translator_.Translate(*fname);
        } else {
            unsigned long long fo = 0;
            if (!GetUInt(ev, L"FileObject", fo)) GetUInt(ev, L"FileKey", fo);
            if (fo != 0) ResolveFileObject(fo, path);
        }
        root.emplace_back("ppid", JsonValue());
        root.emplace_back("path", path.empty() ? JsonValue()
                                               : JsonValue(WideToUtf8(path)));
        root.emplace_back("target", JsonValue());
        root.emplace_back("details", JsonValue(DecodeDetails(
                                        ev, {L"FileName", L"OpenPath",
                                             L"FilePath"})));
    } else if (kind_w == L"registry") {
        const std::wstring* key = GetString(ev, L"KeyName");
        if (!key) key = GetString(ev, L"RelativeName");
        if (!key) key = GetString(ev, L"BaseName");
        root.emplace_back("ppid", JsonValue());
        root.emplace_back("path", JsonValue());
        root.emplace_back("target",
                          (key && !key->empty()) ? JsonValue(WideToUtf8(*key))
                                                  : JsonValue());
        root.emplace_back("details", JsonValue(DecodeDetails(ev, {})));
    } else if (kind_w == L"process") {
        unsigned long long ppid_u = 0;
        long long ppid_v = 0;
        bool have_ppid =
            GetUInt(ev, L"ParentProcessID", ppid_u) ||
            GetUInt(ev, L"ParentProcessId", ppid_u);
        if (!have_ppid && GetInt(ev, L"ParentProcessID", ppid_v)) {
            ppid_u = static_cast<unsigned long long>(ppid_v);
            have_ppid = true;
        }
        const std::wstring* image = GetString(ev, L"ImageName");
        if (!image) image = GetString(ev, L"ImageFileName");
        std::wstring image_translated;
        if (image && !image->empty()) {
            image_translated = translator_.Translate(*image);
        }
        root.emplace_back("ppid",
                          have_ppid ? JsonValue(static_cast<long long>(ppid_u))
                                    : JsonValue());
        root.emplace_back("path",
                          image_translated.empty()
                              ? JsonValue()
                              : JsonValue(WideToUtf8(image_translated)));
        root.emplace_back("target", JsonValue());
        root.emplace_back("details", JsonValue(DecodeDetails(ev, {})));
    } else {  // network
        unsigned long long saddr = 0, daddr = 0, sport = 0, dport = 0,
                           size = 0;
        bool has_s = GetUInt(ev, L"saddr", saddr) ||
                     GetUInt(ev, L"SourceAddress", saddr);
        bool has_d = GetUInt(ev, L"daddr", daddr) ||
                     GetUInt(ev, L"DestinationAddress", daddr);
        GetUInt(ev, L"sport", sport) || GetUInt(ev, L"SourcePort", sport);
        GetUInt(ev, L"dport", dport) || GetUInt(ev, L"DestinationPort", dport);
        GetUInt(ev, L"size", size) || GetUInt(ev, L"Size", size);

        std::string src;
        if (has_s) {
            src = FormatIpv4(saddr);
            if (sport != 0) {
                src.push_back(':');
                src += std::to_string(sport);
            }
        }
        std::string target_s;
        if (has_d) {
            target_s = FormatIpv4(daddr);
            if (dport != 0) {
                target_s.push_back(':');
                target_s += std::to_string(dport);
            }
        }

        root.emplace_back("ppid", JsonValue());
        root.emplace_back("path", JsonValue());
        root.emplace_back("target", target_s.empty()
                                        ? JsonValue()
                                        : JsonValue(target_s));
        JsonObject details;
        if (!src.empty()) details.emplace_back("src", JsonValue(src));
        if (size != 0)
            details.emplace_back("size", JsonValue(static_cast<long long>(size)));
        for (auto&& p : DecodeDetails(ev, {L"saddr", L"daddr", L"sport",
                                           L"dport", L"SourceAddress",
                                           L"DestinationAddress",
                                           L"SourcePort", L"DestinationPort",
                                           L"size", L"Size"})) {
            details.emplace_back(std::move(p));
        }
        root.emplace_back("details", JsonValue(std::move(details)));
    }

    std::string out_line;
    out_line.reserve(256);
    JsonValue(std::move(root)).Serialize(out_line);
    out_line.push_back('\n');

    {
        std::lock_guard<std::mutex> lock(StdoutMutex());
        std::fwrite(out_line.data(), 1, out_line.size(), stdout);
        std::fflush(stdout);
    }
}

void EventConsumer::TouchFileObject(uint64_t file_object, std::wstring path) {
    std::lock_guard<std::mutex> lock(file_cache_mu_);
    auto it = file_lru_pos_.find(file_object);
    if (it != file_lru_pos_.end()) {
        file_lru_.erase(it->second);
    }
    file_lru_.push_front(file_object);
    file_lru_pos_[file_object] = file_lru_.begin();
    file_paths_[file_object] = std::move(path);
    while (file_lru_.size() > kFileCacheCap) {
        uint64_t evict = file_lru_.back();
        file_lru_.pop_back();
        file_lru_pos_.erase(evict);
        file_paths_.erase(evict);
    }
}

bool EventConsumer::ResolveFileObject(uint64_t file_object,
                                      std::wstring& out) const {
    std::lock_guard<std::mutex> lock(file_cache_mu_);
    auto it = file_paths_.find(file_object);
    if (it == file_paths_.end()) return false;
    out = it->second;
    auto pos_it = file_lru_pos_.find(file_object);
    if (pos_it != file_lru_pos_.end()) {
        // const_cast: LRU bookkeeping is logically const for the resolver.
        auto& lru = const_cast<std::list<uint64_t>&>(file_lru_);
        auto& positions =
            const_cast<std::unordered_map<uint64_t,
                                          std::list<uint64_t>::iterator>&>(
                file_lru_pos_);
        lru.erase(pos_it->second);
        lru.push_front(file_object);
        positions[file_object] = lru.begin();
    }
    return true;
}

void EventConsumer::ForgetFileObject(uint64_t file_object) {
    std::lock_guard<std::mutex> lock(file_cache_mu_);
    auto pos_it = file_lru_pos_.find(file_object);
    if (pos_it != file_lru_pos_.end()) {
        file_lru_.erase(pos_it->second);
        file_lru_pos_.erase(pos_it);
    }
    file_paths_.erase(file_object);
}

}  // namespace tracker
