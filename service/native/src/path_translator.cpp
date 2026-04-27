#include "path_translator.hpp"

#include <windows.h>

#include <algorithm>
#include <cwctype>

namespace tracker {

namespace {

constexpr const wchar_t* kUncPrefixes[] = {
    L"\\device\\mup",
    L"\\device\\lanmanredirector",
};

std::wstring ToLower(const std::wstring& s) {
    std::wstring out = s;
    std::transform(out.begin(), out.end(), out.begin(),
                   [](wchar_t ch) { return std::towlower(ch); });
    return out;
}

}  // namespace

void PathTranslator::BuildFromSystem() {
    mapping_.clear();
    wchar_t buf[1024];
    for (wchar_t letter = L'A'; letter <= L'Z'; ++letter) {
        wchar_t name[3] = {letter, L':', 0};
        DWORD len = QueryDosDeviceW(name, buf, 1024);
        if (len > 0) {
            std::wstring target(buf);
            if (!target.empty()) {
                mapping_.emplace_back(ToLower(target), std::wstring(name));
            }
        }
    }
    std::sort(mapping_.begin(), mapping_.end(),
              [](const auto& a, const auto& b) {
                  return a.first.size() > b.first.size();
              });
}

void PathTranslator::AddMapping(std::wstring nt_prefix_lower,
                                std::wstring dos_letter) {
    mapping_.emplace_back(std::move(nt_prefix_lower), std::move(dos_letter));
    std::sort(mapping_.begin(), mapping_.end(),
              [](const auto& a, const auto& b) {
                  return a.first.size() > b.first.size();
              });
}

std::wstring PathTranslator::Translate(const std::wstring& path) const {
    if (path.empty()) return path;
    std::wstring lowered = ToLower(path);

    // UNC translation first.
    for (const wchar_t* unc : kUncPrefixes) {
        std::wstring prefix(unc);
        if (lowered.size() >= prefix.size() &&
            lowered.compare(0, prefix.size(), prefix) == 0) {
            std::wstring remainder = path.substr(prefix.size());
            // remainder typically starts with "\"; produce "\\server\share\..."
            if (!remainder.empty() && remainder[0] == L'\\') {
                return L"\\" + remainder;
            }
            return L"\\\\" + remainder;
        }
    }

    for (const auto& [nt_prefix, dos_letter] : mapping_) {
        if (lowered.size() >= nt_prefix.size() &&
            lowered.compare(0, nt_prefix.size(), nt_prefix) == 0) {
            return dos_letter + path.substr(nt_prefix.size());
        }
    }
    return path;
}

}  // namespace tracker
