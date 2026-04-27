#include "tdh_parser.hpp"

#include <windows.h>
#include <tdh.h>

#include <cstring>
#include <vector>

namespace tracker {

namespace {

// Read a property's raw bytes via TdhGetProperty.
bool ReadPropertyBytes(PEVENT_RECORD record, PTRACE_EVENT_INFO info,
                       ULONG property_index, std::vector<uint8_t>& out_bytes,
                       ULONG& out_inner_type) {
    PROPERTY_DATA_DESCRIPTOR desc{};
    desc.PropertyName = reinterpret_cast<ULONGLONG>(
        reinterpret_cast<PBYTE>(info) +
        info->EventPropertyInfoArray[property_index].NameOffset);
    desc.ArrayIndex = ULONG_MAX;

    ULONG size = 0;
    ULONG status = TdhGetPropertySize(record, 0, nullptr, 1, &desc, &size);
    if (status != ERROR_SUCCESS || size == 0) {
        return false;
    }
    out_bytes.assign(size, 0);
    status = TdhGetProperty(record, 0, nullptr, 1, &desc, size,
                            out_bytes.data());
    if (status != ERROR_SUCCESS) {
        return false;
    }
    out_inner_type = info->EventPropertyInfoArray[property_index].nonStructType.InType;
    return true;
}

PropertyValue InterpretProperty(ULONG in_type, const std::vector<uint8_t>& bytes) {
    switch (in_type) {
        case TDH_INTYPE_UNICODESTRING: {
            // bytes is a wide-string, possibly null-terminated.
            if (bytes.empty()) return std::wstring();
            size_t wchars = bytes.size() / sizeof(wchar_t);
            const wchar_t* data = reinterpret_cast<const wchar_t*>(bytes.data());
            // Strip a trailing NUL if present.
            while (wchars > 0 && data[wchars - 1] == L'\0') --wchars;
            return std::wstring(data, wchars);
        }
        case TDH_INTYPE_ANSISTRING: {
            if (bytes.empty()) return std::wstring();
            size_t n = bytes.size();
            const char* p = reinterpret_cast<const char*>(bytes.data());
            while (n > 0 && p[n - 1] == '\0') --n;
            int wlen = MultiByteToWideChar(CP_ACP, 0, p, static_cast<int>(n),
                                           nullptr, 0);
            std::wstring w(static_cast<size_t>(wlen), L'\0');
            MultiByteToWideChar(CP_ACP, 0, p, static_cast<int>(n), w.data(),
                                wlen);
            return w;
        }
        case TDH_INTYPE_INT8:
            if (bytes.size() >= 1)
                return static_cast<long long>(*reinterpret_cast<const int8_t*>(bytes.data()));
            return std::monostate{};
        case TDH_INTYPE_UINT8:
            if (bytes.size() >= 1)
                return static_cast<unsigned long long>(*reinterpret_cast<const uint8_t*>(bytes.data()));
            return std::monostate{};
        case TDH_INTYPE_INT16:
            if (bytes.size() >= 2)
                return static_cast<long long>(*reinterpret_cast<const int16_t*>(bytes.data()));
            return std::monostate{};
        case TDH_INTYPE_UINT16:
            if (bytes.size() >= 2)
                return static_cast<unsigned long long>(*reinterpret_cast<const uint16_t*>(bytes.data()));
            return std::monostate{};
        case TDH_INTYPE_INT32:
        case TDH_INTYPE_HEXINT32:
            if (bytes.size() >= 4)
                return static_cast<long long>(*reinterpret_cast<const int32_t*>(bytes.data()));
            return std::monostate{};
        case TDH_INTYPE_UINT32:
            if (bytes.size() >= 4)
                return static_cast<unsigned long long>(*reinterpret_cast<const uint32_t*>(bytes.data()));
            return std::monostate{};
        case TDH_INTYPE_INT64:
            if (bytes.size() >= 8)
                return static_cast<long long>(*reinterpret_cast<const int64_t*>(bytes.data()));
            return std::monostate{};
        case TDH_INTYPE_UINT64:
        case TDH_INTYPE_HEXINT64:
        case TDH_INTYPE_POINTER:
            if (bytes.size() >= 8)
                return static_cast<unsigned long long>(*reinterpret_cast<const uint64_t*>(bytes.data()));
            return std::monostate{};
        case TDH_INTYPE_BOOLEAN:
            if (bytes.size() >= 4)
                return static_cast<unsigned long long>(
                    *reinterpret_cast<const uint32_t*>(bytes.data()) ? 1u : 0u);
            return std::monostate{};
        case TDH_INTYPE_GUID: {
            if (bytes.size() < sizeof(GUID)) return std::monostate{};
            const GUID* g = reinterpret_cast<const GUID*>(bytes.data());
            wchar_t buf[64];
            int n = swprintf_s(buf, 64,
                               L"{%08lX-%04X-%04X-%02X%02X-%02X%02X%02X%02X%02X%02X}",
                               g->Data1, g->Data2, g->Data3, g->Data4[0],
                               g->Data4[1], g->Data4[2], g->Data4[3],
                               g->Data4[4], g->Data4[5], g->Data4[6],
                               g->Data4[7]);
            return std::wstring(buf, n > 0 ? static_cast<size_t>(n) : 0);
        }
        case TDH_INTYPE_BINARY:
            return bytes;
        default:
            // Fallback: keep raw bytes — caller may interpret if it cares.
            return bytes;
    }
}

}  // namespace

bool DecodeEvent(PEVENT_RECORD record, DecodedEvent& out) {
    out.provider_guid = record->EventHeader.ProviderId;
    out.event_id = record->EventHeader.EventDescriptor.Id;
    out.opcode = record->EventHeader.EventDescriptor.Opcode;
    out.level = record->EventHeader.EventDescriptor.Level;
    out.process_id = record->EventHeader.ProcessId;
    out.thread_id = record->EventHeader.ThreadId;
    ULARGE_INTEGER u;
    u.LowPart = record->EventHeader.TimeStamp.LowPart;
    u.HighPart = static_cast<ULONG>(record->EventHeader.TimeStamp.HighPart);
    out.timestamp_ft = u.QuadPart;
    out.props.clear();

    ULONG buffer_size = 0;
    ULONG status = TdhGetEventInformation(record, 0, nullptr, nullptr,
                                          &buffer_size);
    if (status != ERROR_INSUFFICIENT_BUFFER) {
        return false;
    }
    std::vector<uint8_t> info_buf(buffer_size, 0);
    PTRACE_EVENT_INFO info = reinterpret_cast<PTRACE_EVENT_INFO>(info_buf.data());
    status = TdhGetEventInformation(record, 0, nullptr, info, &buffer_size);
    if (status != ERROR_SUCCESS) {
        return false;
    }

    for (ULONG i = 0; i < info->TopLevelPropertyCount; ++i) {
        const EVENT_PROPERTY_INFO& pi = info->EventPropertyInfoArray[i];
        // Skip nested struct properties — flat read only.
        if (pi.Flags & PropertyStruct) {
            continue;
        }
        const wchar_t* name = reinterpret_cast<const wchar_t*>(
            reinterpret_cast<PBYTE>(info) + pi.NameOffset);

        std::vector<uint8_t> raw;
        ULONG in_type = 0;
        if (!ReadPropertyBytes(record, info, i, raw, in_type)) {
            continue;
        }
        out.props[std::wstring(name)] = InterpretProperty(in_type, raw);
    }
    return true;
}

const std::wstring* GetString(const DecodedEvent& ev, const wchar_t* key) {
    auto it = ev.props.find(key);
    if (it == ev.props.end()) return nullptr;
    return std::get_if<std::wstring>(&it->second);
}

bool GetUInt(const DecodedEvent& ev, const wchar_t* key,
             unsigned long long& out) {
    auto it = ev.props.find(key);
    if (it == ev.props.end()) return false;
    if (auto* p = std::get_if<unsigned long long>(&it->second)) {
        out = *p;
        return true;
    }
    if (auto* p = std::get_if<long long>(&it->second)) {
        out = static_cast<unsigned long long>(*p);
        return true;
    }
    return false;
}

bool GetInt(const DecodedEvent& ev, const wchar_t* key, long long& out) {
    auto it = ev.props.find(key);
    if (it == ev.props.end()) return false;
    if (auto* p = std::get_if<long long>(&it->second)) {
        out = *p;
        return true;
    }
    if (auto* p = std::get_if<unsigned long long>(&it->second)) {
        out = static_cast<long long>(*p);
        return true;
    }
    return false;
}

}  // namespace tracker
