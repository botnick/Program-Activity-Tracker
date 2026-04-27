// Bounded set of PIDs we follow. Mutated when a process_start event whose
// parent is already in the set arrives, and queried on every event to gate
// emission. Optionally validates create-time so a recycled PID isn't
// accepted as the same logical process.
#pragma once

#include <windows.h>

#include <chrono>
#include <mutex>
#include <optional>
#include <unordered_map>
#include <unordered_set>

namespace tracker {

class PidFilter {
public:
    void AddRoot(DWORD pid) {
        std::lock_guard<std::mutex> lock(mu_);
        pids_.insert(pid);
    }

    void Remove(DWORD pid) {
        std::lock_guard<std::mutex> lock(mu_);
        pids_.erase(pid);
        create_times_.erase(pid);
    }

    bool Contains(DWORD pid) const {
        std::lock_guard<std::mutex> lock(mu_);
        return pids_.count(pid) > 0;
    }

    // Add `child` if `parent` is currently tracked. Returns true if added.
    bool AddIfParentTracked(DWORD parent, DWORD child) {
        std::lock_guard<std::mutex> lock(mu_);
        if (pids_.count(parent) == 0) return false;
        pids_.insert(child);
        return true;
    }

    size_t Size() const {
        std::lock_guard<std::mutex> lock(mu_);
        return pids_.size();
    }

    // PID-reuse protection. expected_create_time is in 100ns ticks since
    // 1601-01-01 (FILETIME). Returns true iff process at `pid` matches
    // within 1 second, OR we cannot read its create time (treat as unknown).
    bool VerifyCreateTime(DWORD pid, ULONGLONG expected_filetime_ticks) {
        ULONGLONG cached;
        {
            std::lock_guard<std::mutex> lock(mu_);
            auto it = create_times_.find(pid);
            if (it != create_times_.end()) {
                cached = it->second;
                return WithinOneSecond(cached, expected_filetime_ticks);
            }
        }

        HANDLE h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
        if (h == nullptr) {
            return true;  // unknown -> accept
        }
        FILETIME create{}, exit{}, kernel{}, user{};
        BOOL ok = GetProcessTimes(h, &create, &exit, &kernel, &user);
        CloseHandle(h);
        if (!ok) return true;
        ULARGE_INTEGER u;
        u.LowPart = create.dwLowDateTime;
        u.HighPart = create.dwHighDateTime;
        cached = u.QuadPart;
        {
            std::lock_guard<std::mutex> lock(mu_);
            create_times_[pid] = cached;
        }
        return WithinOneSecond(cached, expected_filetime_ticks);
    }

private:
    static bool WithinOneSecond(ULONGLONG a, ULONGLONG b) {
        // FILETIME is 100ns ticks; 1 second = 10,000,000 ticks.
        ULONGLONG diff = (a > b) ? (a - b) : (b - a);
        return diff <= 10'000'000ULL;
    }

    mutable std::mutex mu_;
    std::unordered_set<DWORD> pids_;
    std::unordered_map<DWORD, ULONGLONG> create_times_;
};

}  // namespace tracker
