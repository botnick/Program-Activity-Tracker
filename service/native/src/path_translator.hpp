// NT device path -> DOS letter / UNC translation.
#pragma once

#include <string>
#include <vector>

namespace tracker {

class PathTranslator {
public:
    // Build the DOS-letter map by querying QueryDosDeviceW for A..Z.
    void BuildFromSystem();

    // Translate an NT path. UNC: "\Device\Mup\server\share\..." ->
    // "\\server\share\...". Drive: "\Device\HarddiskVolume3\Users\..." ->
    // "C:\Users\...". Other paths are returned unchanged.
    std::wstring Translate(const std::wstring& path) const;

    // Inject a synthetic mapping for tests / hand-rolled callers.
    void AddMapping(std::wstring nt_prefix_lower, std::wstring dos_letter);

private:
    // Sorted longest-prefix-first. Each pair is (lowercased nt prefix, dos
    // letter without trailing backslash).
    std::vector<std::pair<std::wstring, std::wstring>> mapping_;
};

}  // namespace tracker
