"""Windows EXE icon extraction.

Pure-Python implementation backed by ``ctypes``. The public surface is small:

* :func:`extract_icon_png` — pull the primary icon out of a Windows EXE,
  return PNG bytes (or ``None`` on any failure).
* :func:`get_or_extract_icon` — same but with a disk cache keyed off
  ``SHA1(normcase(exe_path))``.
* :data:`TRANSPARENT_PNG` — 1x1 transparent fallback so the HTTP route
  never has to return a 5xx.

The Win32 path is: ``SHGetFileInfoW`` -> ``HICON``, ``GetIconInfo`` ->
color/mask bitmaps, ``GetDIBits`` -> top-down 32bpp BGRA buffer, then
hand-rolled PNG (deflate + chunked container).

On non-Windows platforms every public function returns ``None`` so callers
can keep the same code path for tests / dev.
"""

from __future__ import annotations

import contextlib
import ctypes
import hashlib
import os
import struct
import sys
import zlib
from ctypes import wintypes
from pathlib import Path

# ---- Win32 constants -------------------------------------------------------

SHGFI_ICON = 0x100
SHGFI_LARGEICON = 0x0  # 32x32
SHGFI_SMALLICON = 0x1  # 16x16
SHGFI_USEFILEATTRIBUTES = 0x10
FILE_ATTRIBUTE_NORMAL = 0x80
DIB_RGB_COLORS = 0
BI_RGB = 0


# ---- Win32 structs ---------------------------------------------------------


class SHFILEINFOW(ctypes.Structure):
    _fields_ = [
        ("hIcon", wintypes.HICON),
        ("iIcon", ctypes.c_int),
        ("dwAttributes", wintypes.DWORD),
        ("szDisplayName", wintypes.WCHAR * 260),
        ("szTypeName", wintypes.WCHAR * 80),
    ]


class ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", wintypes.BOOL),
        ("xHotspot", wintypes.DWORD),
        ("yHotspot", wintypes.DWORD),
        ("hbmMask", wintypes.HBITMAP),
        ("hbmColor", wintypes.HBITMAP),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    # bmiColors holds the BI_BITFIELDS color masks; for BI_RGB it's unused
    # but the struct must still be sized to include it.
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class BITMAP(ctypes.Structure):
    _fields_ = [
        ("bmType", wintypes.LONG),
        ("bmWidth", wintypes.LONG),
        ("bmHeight", wintypes.LONG),
        ("bmWidthBytes", wintypes.LONG),
        ("bmPlanes", wintypes.WORD),
        ("bmBitsPixel", wintypes.WORD),
        ("bmBits", ctypes.c_void_p),
    ]


# ---- Win32 binding ---------------------------------------------------------

if sys.platform == "win32":
    _shell32 = ctypes.windll.shell32
    _user32 = ctypes.windll.user32
    _gdi32 = ctypes.windll.gdi32

    _shell32.SHGetFileInfoW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(SHFILEINFOW),
        wintypes.UINT,
        wintypes.UINT,
    ]
    _shell32.SHGetFileInfoW.restype = ctypes.c_void_p  # DWORD_PTR

    _user32.GetIconInfo.argtypes = [wintypes.HICON, ctypes.POINTER(ICONINFO)]
    _user32.GetIconInfo.restype = wintypes.BOOL

    _user32.DestroyIcon.argtypes = [wintypes.HICON]
    _user32.DestroyIcon.restype = wintypes.BOOL

    _user32.GetDC.argtypes = [wintypes.HWND]
    _user32.GetDC.restype = wintypes.HDC

    _user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    _user32.ReleaseDC.restype = ctypes.c_int

    _gdi32.GetObjectW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p]
    _gdi32.GetObjectW.restype = ctypes.c_int

    _gdi32.GetDIBits.argtypes = [
        wintypes.HDC,
        wintypes.HBITMAP,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.c_void_p,
        ctypes.POINTER(BITMAPINFO),
        wintypes.UINT,
    ]
    _gdi32.GetDIBits.restype = ctypes.c_int

    _gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    _gdi32.DeleteObject.restype = wintypes.BOOL
else:  # pragma: no cover - non-Windows
    _shell32 = None
    _user32 = None
    _gdi32 = None


# ---- PNG encoder -----------------------------------------------------------


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)


def _encode_png(width: int, height: int, bgra: bytes) -> bytes:
    """Encode 32-bit BGRA bytes (top-down) as a PNG.

    PNG wants RGBA top-down; we convert BGRA -> RGBA, prepend a filter
    byte 0 per row, deflate the result, and wrap it in IHDR/IDAT/IEND
    chunks behind the 8-byte signature.
    """
    rows = bytearray()
    stride = width * 4
    for y in range(height):
        rows.append(0)  # filter: None
        row_off = y * stride
        for x in range(width):
            base = row_off + x * 4
            b = bgra[base]
            g = bgra[base + 1]
            r = bgra[base + 2]
            a = bgra[base + 3]
            rows.append(r)
            rows.append(g)
            rows.append(b)
            rows.append(a)
    idat = zlib.compress(bytes(rows), level=6)
    sig = b"\x89PNG\r\n\x1a\n"
    # 8bpc, color type 6 = RGBA, no compression/filter/interlace overrides.
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return sig + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", idat) + _png_chunk(b"IEND", b"")


# ---- Public extraction API -------------------------------------------------


def extract_icon_png(exe_path: str, size: int = 32) -> bytes | None:
    """Return the EXE's primary icon as PNG bytes, or ``None`` if unavailable."""
    if sys.platform != "win32" or _shell32 is None:
        return None
    if not exe_path or not os.path.isfile(exe_path):
        return None

    info = SHFILEINFOW()
    flags = SHGFI_ICON | (SHGFI_LARGEICON if size >= 32 else SHGFI_SMALLICON)
    res = _shell32.SHGetFileInfoW(
        exe_path, 0, ctypes.byref(info), ctypes.sizeof(info), flags
    )
    if not res or not info.hIcon:
        # Fall back to USEFILEATTRIBUTES, which lets the shell synthesize
        # an icon from the file's class even if the on-disk file is awkward.
        res = _shell32.SHGetFileInfoW(
            exe_path,
            FILE_ATTRIBUTE_NORMAL,
            ctypes.byref(info),
            ctypes.sizeof(info),
            flags | SHGFI_USEFILEATTRIBUTES,
        )
        if not res or not info.hIcon:
            return None

    try:
        ii = ICONINFO()
        if not _user32.GetIconInfo(info.hIcon, ctypes.byref(ii)):
            return None
        try:
            target = ii.hbmColor or ii.hbmMask
            if not target:
                return None

            bm = BITMAP()
            if not _gdi32.GetObjectW(target, ctypes.sizeof(bm), ctypes.byref(bm)):
                return None
            w, h = bm.bmWidth, bm.bmHeight
            if not w or not h:
                return None

            bi = BITMAPINFO()
            bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bi.bmiHeader.biWidth = w
            bi.bmiHeader.biHeight = -h  # negative => top-down rows
            bi.bmiHeader.biPlanes = 1
            bi.bmiHeader.biBitCount = 32
            bi.bmiHeader.biCompression = BI_RGB
            bi.bmiHeader.biSizeImage = 0

            buf = (ctypes.c_ubyte * (w * h * 4))()
            hdc = _user32.GetDC(0)
            try:
                rows = _gdi32.GetDIBits(
                    hdc, target, 0, h, buf, ctypes.byref(bi), DIB_RGB_COLORS
                )
                if rows == 0:
                    return None
            finally:
                _user32.ReleaseDC(0, hdc)

            return _encode_png(w, h, bytes(buf))
        finally:
            if ii.hbmColor:
                _gdi32.DeleteObject(ii.hbmColor)
            if ii.hbmMask:
                _gdi32.DeleteObject(ii.hbmMask)
    finally:
        _user32.DestroyIcon(info.hIcon)


# ---- Disk cache ------------------------------------------------------------


def cache_key(exe_path: str) -> str:
    """SHA1 of the case-normalized exe path, encoded as UTF-16LE.

    Windows file paths are case-insensitive, so two callers requesting
    ``C:\\Windows\\notepad.exe`` and ``c:\\windows\\notepad.exe`` should
    hit the same cache row.
    """
    return hashlib.sha1(os.path.normcase(exe_path).encode("utf-16le")).hexdigest()


def cache_dir() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    out = repo_root / "cache" / "icons"
    out.mkdir(parents=True, exist_ok=True)
    return out


def get_or_extract_icon(exe_path: str, size: int = 32) -> bytes | None:
    """Return cached PNG bytes for ``exe_path`` or extract + cache them."""
    key = cache_key(exe_path)
    cached = cache_dir() / f"{key}.png"
    if cached.exists():
        with contextlib.suppress(OSError):
            return cached.read_bytes()
    png = extract_icon_png(exe_path, size)
    if png is None:
        return None
    with contextlib.suppress(OSError):
        cached.write_bytes(png)
    return png


# ---- Fallback PNG ----------------------------------------------------------

# 1x1 fully transparent PNG. The HTTP route serves this whenever extraction
# fails, so the UI never has to handle a 4xx/5xx for a missing icon. Built
# at import time via the same encoder used for real icons; this guarantees
# the bytes round-trip through any conformant PNG decoder.
TRANSPARENT_PNG = _encode_png(1, 1, bytes([0, 0, 0, 0]))
