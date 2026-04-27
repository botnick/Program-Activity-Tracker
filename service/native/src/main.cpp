// tracker_capture.exe — native ETW backend for service/capture_service.py.
//
// CLI:
//   tracker_capture.exe --pid <int> [--pid-create-time <epoch_ms>]
//                       [--engines file,registry,process,network]
//                       [--session-name <name>]
//                       [--no-orphan-cleanup]
//
// Emits one JSON line per event to stdout; logs / errors to stderr.

#include <windows.h>
#include <io.h>
#include <fcntl.h>

#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <set>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#include "etw_session.hpp"
#include "event_consumer.hpp"
#include "json_writer.hpp"
#include "path_translator.hpp"
#include "pid_filter.hpp"
#include "provider_guids.hpp"

namespace {

std::atomic<bool> g_shutdown{false};
std::atomic<tracker::EtwSession*> g_session{nullptr};

BOOL WINAPI CtrlHandler(DWORD type) {
    switch (type) {
        case CTRL_C_EVENT:
        case CTRL_BREAK_EVENT:
        case CTRL_CLOSE_EVENT:
        case CTRL_SHUTDOWN_EVENT:
        case CTRL_LOGOFF_EVENT: {
            g_shutdown = true;
            tracker::EtwSession* s = g_session.load();
            if (s != nullptr) s->Stop();
            return TRUE;
        }
        default:
            return FALSE;
    }
}

void LogE(const std::string& msg) {
    std::fprintf(stderr, "%s\n", msg.c_str());
    std::fflush(stderr);
}

void LogI(const std::string& msg) {
    std::fprintf(stderr, "[info] %s\n", msg.c_str());
    std::fflush(stderr);
}

struct Args {
    DWORD pid = 0;
    ULONGLONG create_time_ft = 0;  // 0 = no PID-reuse check
    bool engine_file = true;
    bool engine_registry = true;
    bool engine_process = true;
    bool engine_network = true;
    std::wstring session_name;
    bool no_orphan_cleanup = false;
    int stats_interval_ms = 1000;  // 0 disables heartbeat
};

std::wstring DefaultSessionName(DWORD pid) {
    auto epoch = static_cast<long long>(
        std::chrono::duration_cast<std::chrono::seconds>(
            std::chrono::system_clock::now().time_since_epoch())
            .count());
    wchar_t buf[64];
    swprintf_s(buf, 64, L"tracker_capture-%lu-%lld", pid, epoch);
    return std::wstring(buf);
}

std::vector<std::wstring> Split(const std::wstring& s, wchar_t delim) {
    std::vector<std::wstring> out;
    std::wstring cur;
    for (wchar_t ch : s) {
        if (ch == delim) {
            out.push_back(cur);
            cur.clear();
        } else {
            cur.push_back(ch);
        }
    }
    if (!cur.empty()) out.push_back(cur);
    return out;
}

bool ParseArgs(int argc, wchar_t** argv, Args& args) {
    for (int i = 1; i < argc; ++i) {
        std::wstring a = argv[i];
        auto next = [&](std::wstring& dst) -> bool {
            if (i + 1 >= argc) return false;
            dst = argv[++i];
            return true;
        };
        if (a == L"--pid") {
            std::wstring v;
            if (!next(v)) return false;
            args.pid = static_cast<DWORD>(std::wcstoul(v.c_str(), nullptr, 10));
        } else if (a == L"--pid-create-time") {
            std::wstring v;
            if (!next(v)) return false;
            // Input is epoch milliseconds. Convert to FILETIME ticks
            // (100ns since 1601-01-01).
            long long ms = std::wcstoll(v.c_str(), nullptr, 10);
            // FILETIME(epoch=1970-01-01) base = 116444736000000000.
            args.create_time_ft =
                static_cast<ULONGLONG>(ms) * 10'000ULL + 116'444'736'000'000'000ULL;
        } else if (a == L"--engines") {
            std::wstring v;
            if (!next(v)) return false;
            args.engine_file = args.engine_registry = args.engine_process =
                args.engine_network = false;
            for (const auto& e : Split(v, L',')) {
                if (e == L"file") args.engine_file = true;
                else if (e == L"registry") args.engine_registry = true;
                else if (e == L"process") args.engine_process = true;
                else if (e == L"network") args.engine_network = true;
            }
        } else if (a == L"--session-name") {
            if (!next(args.session_name)) return false;
        } else if (a == L"--no-orphan-cleanup") {
            args.no_orphan_cleanup = true;
        } else if (a == L"--stats-interval-ms") {
            std::wstring v;
            if (!next(v)) return false;
            long long ms = std::wcstoll(v.c_str(), nullptr, 10);
            if (ms < 0) ms = 0;
            args.stats_interval_ms = static_cast<int>(ms);
        } else if (a == L"--help" || a == L"-h") {
            std::fprintf(stderr,
                         "tracker_capture --pid <int> "
                         "[--pid-create-time <epoch_ms>] "
                         "[--engines file,registry,process,network] "
                         "[--session-name <name>] [--no-orphan-cleanup] "
                         "[--stats-interval-ms <int>] "
                         "[--version|-V]\n");
            return false;
        } else {
            LogE("unknown argument: " + tracker::WideToUtf8(a));
            return false;
        }
    }
    if (args.pid == 0) {
        LogE("missing required --pid");
        return false;
    }
    if (args.session_name.empty()) {
        args.session_name = DefaultSessionName(args.pid);
    }
    return true;
}

// Read stdin until EOF on a background thread; flag shutdown when the
// parent closes the pipe.
void StdinWatcher() {
    char buf[64];
    for (;;) {
        DWORD read = 0;
        BOOL ok = ReadFile(GetStdHandle(STD_INPUT_HANDLE), buf, sizeof(buf),
                           &read, nullptr);
        if (!ok || read == 0) {
            g_shutdown = true;
            tracker::EtwSession* s = g_session.load();
            if (s != nullptr) s->Stop();
            return;
        }
    }
}

}  // namespace

int wmain(int argc, wchar_t** argv) {
    // Make stdout binary so we don't get CRLF translation on JSON.
    _setmode(_fileno(stdout), _O_BINARY);

    // --version / -V: print version banner and exit BEFORE doing any other
    // work. Honoured even when other flags are present so the Python wrapper
    // can probe with a single argv. Must precede --help and ParseArgs.
    for (int i = 1; i < argc; ++i) {
        if (std::wcscmp(argv[i], L"--version") == 0 ||
            std::wcscmp(argv[i], L"-V") == 0) {
            std::fprintf(stdout, "tracker_capture %s\n", tracker::kEngineVersion);
            std::fflush(stdout);
            return 0;
        }
    }

    Args args;
    if (!ParseArgs(argc, argv, args)) {
        return 2;
    }

    SetConsoleCtrlHandler(CtrlHandler, TRUE);

    if (!args.no_orphan_cleanup) {
        tracker::EtwSession::SweepOrphans(L"tracker_capture-");
    }

    tracker::PathTranslator translator;
    translator.BuildFromSystem();

    tracker::PidFilter pids;
    pids.AddRoot(args.pid);

    tracker::EtwSession session;
    g_session.store(&session);
    DWORD status = session.Start(args.session_name);
    if (status != ERROR_SUCCESS) {
        char msg[128];
        std::snprintf(msg, sizeof(msg), "failed to start trace: %lu",
                      static_cast<unsigned long>(status));
        LogE(msg);
        return 3;
    }
    LogI("trace session started");

    // Hello-sentinel handshake: emit one JSON line on stdout BEFORE
    // ProcessTrace begins streaming events. The Python wrapper aborts on
    // version mismatch, so this must be the very first stdout line. Only
    // reachable on a successful session.Start (i.e. running elevated) — on
    // ACCESS_DENIED we exit above with no stdout output, which is correct.
    {
        tracker::JsonObject hello;
        hello.emplace_back("type", tracker::JsonValue(std::string("hello")));
        hello.emplace_back("version",
                           tracker::JsonValue(std::string(tracker::kEngineVersion)));
        hello.emplace_back(
            "session_name",
            tracker::JsonValue(tracker::WideToUtf8(args.session_name)));
        hello.emplace_back(
            "target_pid",
            tracker::JsonValue(static_cast<long long>(args.pid)));
        hello.emplace_back(
            "pid",
            tracker::JsonValue(
                static_cast<long long>(GetCurrentProcessId())));
        hello.emplace_back("started_at",
                           tracker::JsonValue(tracker::NowIso8601Utc()));
        std::string line;
        line.reserve(192);
        tracker::JsonValue(std::move(hello)).Serialize(line);
        line.push_back('\n');
        tracker::WriteStdoutLine(line);
    }

    auto enable = [&](const tracker::ProviderRequest& r,
                      const char* name) -> bool {
        DWORD s = session.EnableProvider(r);
        if (s != ERROR_SUCCESS) {
            char msg[128];
            std::snprintf(msg, sizeof(msg),
                          "failed to enable provider %s: %lu", name,
                          static_cast<unsigned long>(s));
            LogE(msg);
            return false;
        }
        return true;
    };

    if (args.engine_file) {
        enable({tracker::kProviderFile, tracker::kFileKeywords,
                TRACE_LEVEL_VERBOSE},
               "file");
    }
    if (args.engine_registry) {
        enable({tracker::kProviderRegistry, tracker::kRegistryKeywords,
                TRACE_LEVEL_VERBOSE},
               "registry");
    }
    if (args.engine_process) {
        enable({tracker::kProviderProcess, tracker::kProcessKeywords,
                TRACE_LEVEL_VERBOSE},
               "process");
    }
    if (args.engine_network) {
        enable({tracker::kProviderNetwork, tracker::kNetworkKeywords,
                TRACE_LEVEL_VERBOSE},
               "network");
    }

    tracker::ConsumerConfig cfg;
    cfg.target_pid = args.pid;
    cfg.target_create_filetime = args.create_time_ft;
    cfg.engine_file = args.engine_file;
    cfg.engine_registry = args.engine_registry;
    cfg.engine_process = args.engine_process;
    cfg.engine_network = args.engine_network;
    cfg.stats_interval_ms = args.stats_interval_ms;

    tracker::EventConsumer consumer(cfg, translator, pids);
    if (!consumer.Start(args.session_name)) {
        LogE("failed to open trace consumer");
        session.Stop();
        return 4;
    }
    LogI("consumer running");

    std::thread stdin_thread(StdinWatcher);
    stdin_thread.detach();

    // Block until shutdown is signalled. Consumer is owned and will be
    // joined by its destructor.
    while (!g_shutdown.load()) {
        std::this_thread::sleep_for(std::chrono::milliseconds(250));
    }

    consumer.Stop();
    session.Stop();
    g_session.store(nullptr);
    LogI("clean shutdown");
    return 0;
}
