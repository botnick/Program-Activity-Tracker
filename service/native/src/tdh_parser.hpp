// Decode an EVENT_RECORD into a flat property map using TDH.
#pragma once

#include <windows.h>
#include <evntcons.h>
#include <evntrace.h>

#include <string>
#include <unordered_map>
#include <variant>
#include <vector>

namespace tracker {

// Each property is decoded into one of these shapes. Strings are wide
// (UTF-16) and translated to UTF-8 at JSON-emit time.
using PropertyValue = std::variant<std::monostate, std::wstring, long long,
                                   unsigned long long, std::vector<uint8_t>>;

struct DecodedEvent {
    GUID provider_guid{};
    USHORT event_id = 0;
    UCHAR opcode = 0;
    UCHAR level = 0;
    DWORD process_id = 0;
    DWORD thread_id = 0;
    ULONGLONG timestamp_ft = 0;  // FILETIME ticks (100ns since 1601-01-01)
    std::unordered_map<std::wstring, PropertyValue> props;
};

// Decode the given record. Returns false if TDH metadata cannot be loaded
// (rare for manifest-based providers, but we tolerate it).
bool DecodeEvent(PEVENT_RECORD record, DecodedEvent& out);

// Convenience accessors. Return std::nullopt-like empty on missing/wrong type.
const std::wstring* GetString(const DecodedEvent& ev, const wchar_t* key);
bool GetUInt(const DecodedEvent& ev, const wchar_t* key, unsigned long long& out);
bool GetInt(const DecodedEvent& ev, const wchar_t* key, long long& out);

}  // namespace tracker
