"""Realistic mock ETW event tuples for unit testing CaptureService.

Each constant is a ``(event_id, data_dict)`` 2-tuple shaped exactly like
what ``pywintrace`` hands to its ``event_callback``: an outer dict with
an ``EventHeader`` sub-dict (ProviderId is a curly-braced GUID string,
ProcessId / ThreadId / TimeStamp are ints), a ``Task Name``, plus the
parsed property fields hoisted to the top level.
"""

from __future__ import annotations

from typing import Any

# Provider GUIDs (must match service.capture_service exactly).
PROVIDER_FILE = "{EDD08927-9CC4-4E65-B970-C2560FB5C289}"
PROVIDER_REGISTRY = "{70EB4F03-C1DE-4F73-A051-33D13D5413BD}"
PROVIDER_PROCESS = "{22FB2CD6-0E7B-422B-A0C7-2FAD1FD0E716}"
PROVIDER_NETWORK = "{7DD42A49-5329-4832-8DFD-43D979153A88}"

# 2020-01-01 00:00:00 UTC as Windows FILETIME (100ns ticks since 1601-01-01).
DEFAULT_TS = 132_223_104_000_000_000


def make_header(
    provider_guid: str,
    process_id: int,
    ts: int = DEFAULT_TS,
    thread_id: int = 4321,
) -> dict[str, Any]:
    """Build a synthetic ``EventHeader`` dict shaped like pywintrace's."""
    return {
        "ProviderId": provider_guid,
        "ProcessId": process_id,
        "ThreadId": thread_id,
        "TimeStamp": ts,
    }


# -- File events -------------------------------------------------------------

FILE_OBJECT_A = 0xABCD0001
FILE_OBJECT_UNC = 0xBEEF0001
FILE_OBJECT_CHILD = 0xCAFE0001
FILE_OBJECT_LRU_BASE = 0x10000

FILE_CREATE: tuple[int, dict[str, Any]] = (
    12,
    {
        "EventHeader": make_header(PROVIDER_FILE, 1234),
        "Task Name": "Create",
        "FileObject": FILE_OBJECT_A,
        "FileName": r"\Device\HarddiskVolume3\Users\test\foo.txt",
        "CreateOptions": 0x60,
        "CreateAttributes": 0x80,
        "ShareAccess": 0x7,
        "IrpPtr": 0xFFFFAA00,
    },
)

FILE_READ: tuple[int, dict[str, Any]] = (
    15,
    {
        "EventHeader": make_header(PROVIDER_FILE, 1234),
        "Task Name": "Read",
        "FileObject": FILE_OBJECT_A,
        "IOSize": 4096,
        "IOFlags": 0x0,
        "ByteOffset": 0,
        "IrpPtr": 0xFFFFAA10,
    },
)

FILE_WRITE: tuple[int, dict[str, Any]] = (
    16,
    {
        "EventHeader": make_header(PROVIDER_FILE, 1234),
        "Task Name": "Write",
        "FileObject": FILE_OBJECT_A,
        "IOSize": 1024,
        "IOFlags": 0x0,
        "ByteOffset": 4096,
        "IrpPtr": 0xFFFFAA20,
    },
)

FILE_CLOSE: tuple[int, dict[str, Any]] = (
    14,
    {
        "EventHeader": make_header(PROVIDER_FILE, 1234),
        "Task Name": "Close",
        "FileObject": FILE_OBJECT_A,
        "FileKey": FILE_OBJECT_A,
        "IrpPtr": 0xFFFFAA30,
    },
)

FILE_CREATE_UNC: tuple[int, dict[str, Any]] = (
    12,
    {
        "EventHeader": make_header(PROVIDER_FILE, 1234),
        "Task Name": "Create",
        "FileObject": FILE_OBJECT_UNC,
        "FileName": r"\Device\Mup\server\share\notes.docx",
        "CreateOptions": 0x60,
        "CreateAttributes": 0x80,
        "ShareAccess": 0x7,
        "IrpPtr": 0xFFFFAA40,
    },
)


# -- Registry events ---------------------------------------------------------

REGISTRY_SET_VALUE: tuple[int, dict[str, Any]] = (
    5,
    {
        "EventHeader": make_header(PROVIDER_REGISTRY, 1234),
        "Task Name": "SetValueKey",
        "KeyName": r"\REGISTRY\USER\S-1-5-21-1\Software\Test",
        "ValueName": "LastRun",
        "Status": 0,
        "Type": 1,
        "DataSize": 16,
    },
)

REGISTRY_DELETE_VALUE: tuple[int, dict[str, Any]] = (
    6,
    {
        "EventHeader": make_header(PROVIDER_REGISTRY, 1234),
        "Task Name": "DeleteValueKey",
        "KeyName": r"\REGISTRY\USER\S-1-5-21-1\Software\Test",
        "ValueName": "LastRun",
        "Status": 0,
    },
)


# -- Process events ----------------------------------------------------------

PROCESS_START_CHILD: tuple[int, dict[str, Any]] = (
    1,
    {
        # The emitting process is the parent (1234); the new child is 9999.
        "EventHeader": make_header(PROVIDER_PROCESS, 1234),
        "Task Name": "ProcessStart",
        "ProcessID": 9999,
        "ParentProcessID": 1234,
        "ImageName": r"C:\Windows\System32\helper.exe",
        "CommandLine": r"helper.exe --do-thing",
        "SessionID": 1,
    },
)

PROCESS_STOP_CHILD: tuple[int, dict[str, Any]] = (
    2,
    {
        "EventHeader": make_header(PROVIDER_PROCESS, 9999),
        "Task Name": "ProcessStop",
        "ProcessID": 9999,
        "ExitStatus": 0,
    },
)

IMAGE_LOAD: tuple[int, dict[str, Any]] = (
    5,
    {
        "EventHeader": make_header(PROVIDER_PROCESS, 1234),
        "Task Name": "ImageLoad",
        "ImageName": "ntdll.dll",
        "ImageBase": 0x7FFD00000000,
        "ImageSize": 0x200000,
        "ProcessID": 1234,
    },
)


# -- Network events ----------------------------------------------------------

# 0x0100007F is little-endian network-order for 127.0.0.1
TCP_CONNECT_V4: tuple[int, dict[str, Any]] = (
    12,
    {
        "EventHeader": make_header(PROVIDER_NETWORK, 1234),
        "Task Name": "KERNEL_NETWORK_TASK_TCPIP",
        "PID": 1234,
        "size": 0,
        "daddr": 0x0100007F,  # 127.0.0.1
        "saddr": 0x0100007F,
        "dport": 0x5000,  # 80 in network-byte-order; we don't byte-swap, value is what comes in
        "sport": 0xC4FE,
        "mss": 1460,
        "sackopt": 1,
        "tsopt": 0,
        "wsopt": 0,
        "rcvwin": 65535,
        "rcvwinscale": 8,
        "sndwinscale": 8,
        "seqnum": 0,
        "connid": 0xDEADBEEF,
    },
)

TCP_CONNECT_V6: tuple[int, dict[str, Any]] = (
    44,
    {
        "EventHeader": make_header(PROVIDER_NETWORK, 1234),
        "Task Name": "KERNEL_NETWORK_TASK_TCPIP",
        "PID": 1234,
        "size": 0,
        "daddr": bytes(15) + b"\x01",  # ::1
        "saddr": bytes(15) + b"\x01",
        "dport": 443,
        "sport": 50001,
        "mss": 1440,
        "connid": 0xCAFEBABE,
    },
)

UDP_SEND_V4: tuple[int, dict[str, Any]] = (
    26,
    {
        "EventHeader": make_header(PROVIDER_NETWORK, 1234),
        "Task Name": "KERNEL_NETWORK_TASK_UDPIP",
        "PID": 1234,
        "size": 64,
        "daddr": 0x0101A8C0,  # 192.168.1.1
        "saddr": 0x0100A8C0,
        "dport": 53,
        "sport": 50050,
        "connid": 0,
    },
)
