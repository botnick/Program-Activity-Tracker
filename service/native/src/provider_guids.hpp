// Provider GUIDs and event-id maps. Must stay in sync with
// service/capture_service.py (the Python pywintrace fallback).
#pragma once

#include <windows.h>

#include <string>
#include <unordered_map>

namespace tracker {

// {EDD08927-9CC4-4E65-B970-C2560FB5C289}  Microsoft-Windows-Kernel-File
inline constexpr GUID kProviderFile = {
    0xEDD08927, 0x9CC4, 0x4E65,
    {0xB9, 0x70, 0xC2, 0x56, 0x0F, 0xB5, 0xC2, 0x89}};

// {70EB4F03-C1DE-4F73-A051-33D13D5413BD}  Microsoft-Windows-Kernel-Registry
inline constexpr GUID kProviderRegistry = {
    0x70EB4F03, 0xC1DE, 0x4F73,
    {0xA0, 0x51, 0x33, 0xD1, 0x3D, 0x54, 0x13, 0xBD}};

// {22FB2CD6-0E7B-422B-A0C7-2FAD1FD0E716}  Microsoft-Windows-Kernel-Process
inline constexpr GUID kProviderProcess = {
    0x22FB2CD6, 0x0E7B, 0x422B,
    {0xA0, 0xC7, 0x2F, 0xAD, 0x1F, 0xD0, 0xE7, 0x16}};

// {7DD42A49-5329-4832-8DFD-43D979153A88}  Microsoft-Windows-Kernel-Network
inline constexpr GUID kProviderNetwork = {
    0x7DD42A49, 0x5329, 0x4832,
    {0x8D, 0xFD, 0x43, 0xD9, 0x79, 0x15, 0x3A, 0x88}};

// Keyword bits — mirror service/capture_service.py:57-69.
inline constexpr ULONGLONG kFileKeywords =
    0x10ULL | 0x20ULL | 0x80ULL | 0x100ULL | 0x200ULL | 0x400ULL | 0x800ULL |
    0x1000ULL;
inline constexpr ULONGLONG kProcessKeywords = 0x10ULL | 0x40ULL | 0x400ULL;
inline constexpr ULONGLONG kRegistryKeywords = 0ULL;
inline constexpr ULONGLONG kNetworkKeywords = 0ULL;

inline const std::unordered_map<unsigned, const wchar_t*>& FileEvents() {
    static const std::unordered_map<unsigned, const wchar_t*> kMap = {
        {12, L"create"},
        {14, L"close"},
        {15, L"read"},
        {16, L"write"},
        {17, L"write"},
        {21, L"set_information"},
        {22, L"set_delete"},
        {23, L"rename"},
        {24, L"directory_enum"},
        {25, L"directory_notify"},
        {26, L"delete"},
        {27, L"rename"},
        {28, L"set_security"},
        {29, L"query_security"},
        {30, L"set_link"},
    };
    return kMap;
}

inline const std::unordered_map<unsigned, const wchar_t*>& RegistryEvents() {
    static const std::unordered_map<unsigned, const wchar_t*> kMap = {
        {1, L"create_key"},
        {2, L"open_key"},
        {3, L"delete_key"},
        {4, L"query_key"},
        {5, L"set_value"},
        {6, L"delete_value"},
        {7, L"query_value"},
        {8, L"enumerate_key"},
        {9, L"enumerate_value"},
        {10, L"kcb_create"},
        {11, L"kcb_delete"},
        {12, L"kcb_rundown_begin"},
        {13, L"kcb_rundown_end"},
        {14, L"set_information"},
        {15, L"flush"},
        {16, L"kcb_dirty"},
        {22, L"close_key"},
    };
    return kMap;
}

inline const std::unordered_map<unsigned, const wchar_t*>& ProcessEvents() {
    static const std::unordered_map<unsigned, const wchar_t*> kMap = {
        {1, L"start"},
        {2, L"stop"},
        {3, L"thread_start"},
        {4, L"thread_stop"},
        {5, L"image_load"},
        {6, L"image_unload"},
    };
    return kMap;
}

inline const std::unordered_map<unsigned, const wchar_t*>& NetworkEvents() {
    static const std::unordered_map<unsigned, const wchar_t*> kMap = {
        {10, L"tcp_send_v4"},
        {11, L"tcp_recv_v4"},
        {12, L"tcp_connect_v4"},
        {13, L"tcp_disconnect_v4"},
        {14, L"tcp_retransmit_v4"},
        {15, L"tcp_accept_v4"},
        {16, L"tcp_reconnect_v4"},
        {17, L"tcp_fail"},
        {26, L"udp_send_v4"},
        {27, L"udp_recv_v4"},
        {28, L"udp_fail"},
        {42, L"tcp_send_v6"},
        {43, L"tcp_recv_v6"},
        {44, L"tcp_connect_v6"},
        {45, L"tcp_disconnect_v6"},
        {46, L"tcp_retransmit_v6"},
        {47, L"tcp_accept_v6"},
        {48, L"tcp_reconnect_v6"},
        {58, L"udp_send_v6"},
        {59, L"udp_recv_v6"},
    };
    return kMap;
}

// Maps a provider GUID to its kind label used in JSON output.
inline const wchar_t* ProviderKind(const GUID& guid) {
    if (IsEqualGUID(guid, kProviderFile)) return L"file";
    if (IsEqualGUID(guid, kProviderRegistry)) return L"registry";
    if (IsEqualGUID(guid, kProviderProcess)) return L"process";
    if (IsEqualGUID(guid, kProviderNetwork)) return L"network";
    return nullptr;
}

}  // namespace tracker
