// Tiny in-house JSON writer used to avoid pulling nlohmann/json (and its
// build-time cost) into a 5-file project. Supports null, bool, integers,
// strings, and nested objects. Strings are escaped per RFC 8259; wide
// strings are converted to UTF-8 via WideCharToMultiByte.
#pragma once

#include <windows.h>

#include <cstdint>
#include <map>
#include <memory>
#include <sstream>
#include <string>
#include <vector>

namespace tracker {

class JsonValue;
using JsonObject = std::vector<std::pair<std::string, JsonValue>>;

class JsonValue {
public:
    enum class Type { Null, Bool, Int, String, Object };

    JsonValue() : type_(Type::Null), bool_(false), int_(0) {}
    explicit JsonValue(std::nullptr_t) : JsonValue() {}
    explicit JsonValue(bool v) : type_(Type::Bool), bool_(v), int_(0) {}
    explicit JsonValue(int v) : type_(Type::Int), bool_(false), int_(v) {}
    explicit JsonValue(long long v) : type_(Type::Int), bool_(false), int_(v) {}
    explicit JsonValue(unsigned long long v)
        : type_(Type::Int), bool_(false), int_(static_cast<long long>(v)) {}
    explicit JsonValue(std::string s)
        : type_(Type::String), bool_(false), int_(0), string_(std::move(s)) {}
    explicit JsonValue(const char* s)
        : type_(Type::String), bool_(false), int_(0), string_(s ? s : "") {}
    explicit JsonValue(JsonObject obj)
        : type_(Type::Object),
          bool_(false),
          int_(0),
          object_(std::make_shared<JsonObject>(std::move(obj))) {}

    Type type() const { return type_; }

    void Serialize(std::string& out) const {
        switch (type_) {
            case Type::Null:
                out.append("null");
                break;
            case Type::Bool:
                out.append(bool_ ? "true" : "false");
                break;
            case Type::Int: {
                char buf[32];
                int n = std::snprintf(buf, sizeof(buf), "%lld",
                                      static_cast<long long>(int_));
                if (n > 0) out.append(buf, static_cast<size_t>(n));
                break;
            }
            case Type::String:
                out.push_back('"');
                EscapeUtf8(string_, out);
                out.push_back('"');
                break;
            case Type::Object:
                out.push_back('{');
                if (object_) {
                    bool first = true;
                    for (const auto& [k, v] : *object_) {
                        if (!first) out.push_back(',');
                        first = false;
                        out.push_back('"');
                        EscapeUtf8(k, out);
                        out.append("\":");
                        v.Serialize(out);
                    }
                }
                out.push_back('}');
                break;
        }
    }

    std::string ToString() const {
        std::string out;
        out.reserve(64);
        Serialize(out);
        return out;
    }

private:
    static void EscapeUtf8(const std::string& s, std::string& out) {
        for (unsigned char c : s) {
            switch (c) {
                case '"':
                    out.append("\\\"");
                    break;
                case '\\':
                    out.append("\\\\");
                    break;
                case '\b':
                    out.append("\\b");
                    break;
                case '\f':
                    out.append("\\f");
                    break;
                case '\n':
                    out.append("\\n");
                    break;
                case '\r':
                    out.append("\\r");
                    break;
                case '\t':
                    out.append("\\t");
                    break;
                default:
                    if (c < 0x20) {
                        char buf[8];
                        int n = std::snprintf(buf, sizeof(buf), "\\u%04x", c);
                        if (n > 0) out.append(buf, static_cast<size_t>(n));
                    } else {
                        out.push_back(static_cast<char>(c));
                    }
            }
        }
    }

    Type type_;
    bool bool_;
    long long int_;
    std::string string_;
    std::shared_ptr<JsonObject> object_;
};

// Convert a wide string (UTF-16) to UTF-8.
inline std::string WideToUtf8(const std::wstring& w) {
    if (w.empty()) return {};
    int bytes = WideCharToMultiByte(CP_UTF8, 0, w.data(),
                                    static_cast<int>(w.size()), nullptr, 0,
                                    nullptr, nullptr);
    if (bytes <= 0) return {};
    std::string out(static_cast<size_t>(bytes), '\0');
    WideCharToMultiByte(CP_UTF8, 0, w.data(), static_cast<int>(w.size()),
                        out.data(), bytes, nullptr, nullptr);
    return out;
}

inline JsonValue WStr(const std::wstring& w) {
    return JsonValue(WideToUtf8(w));
}

}  // namespace tracker
