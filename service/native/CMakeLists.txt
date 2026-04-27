cmake_minimum_required(VERSION 3.20)
project(tracker_capture LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(MSVC)
    add_compile_options(/W4 /permissive- /utf-8)
    add_compile_definitions(UNICODE _UNICODE WIN32_LEAN_AND_MEAN NOMINMAX)
endif()

add_executable(tracker_capture
    src/main.cpp
    src/etw_session.cpp
    src/event_consumer.cpp
    src/tdh_parser.cpp
    src/path_translator.cpp
    src/list_processes.cpp
    src/handle_enumerator.cpp
)

target_link_libraries(tracker_capture PRIVATE
    advapi32
    tdh
    ws2_32
    ole32
    rpcrt4
    psapi
    ntdll
)

target_include_directories(tracker_capture PRIVATE src)

# Embed icon + version info on Windows. Additive block — does not touch
# target_link_libraries / set_target_properties so concurrent edits to those
# (e.g. linking psapi for --list-processes) merge cleanly.
if(WIN32)
    target_sources(tracker_capture PRIVATE
        resources/tracker_capture.rc
    )
endif()
