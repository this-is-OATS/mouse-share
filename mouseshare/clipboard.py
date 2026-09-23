"""Plain-text clipboard access for macOS and Windows."""

import os
import subprocess
import sys


def get_text():
    try:
        return _win_get() if sys.platform == "win32" else _mac_get()
    except Exception:  # clipboard sync is best-effort; never break input sharing
        return None


def set_text(text):
    try:
        if sys.platform == "win32":
            _win_set(text)
        else:
            _mac_set(text)
    except Exception:
        pass


_UTF8_ENV = dict(os.environ, LANG="en_US.UTF-8", LC_CTYPE="UTF-8")


def _mac_get():
    return subprocess.run(["pbpaste"], capture_output=True, env=_UTF8_ENV,
                          timeout=2).stdout.decode("utf-8", "replace")


def _mac_set(text):
    subprocess.run(["pbcopy"], input=text.encode("utf-8"), env=_UTF8_ENV, timeout=2)


CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


def _win_api():
    import ctypes
    from ctypes import wintypes

    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    return ctypes, user32, kernel32


def _win_open(user32):
    import time

    for _ in range(10):  # another app may be holding the clipboard briefly
        if user32.OpenClipboard(None):
            return True
        time.sleep(0.02)
    return False


def _win_get():
    ctypes, user32, kernel32 = _win_api()
    if not _win_open(user32):
        return None
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        pointer = kernel32.GlobalLock(handle)
        try:
            return ctypes.wstring_at(pointer)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def _win_set(text):
    ctypes, user32, kernel32 = _win_api()
    data = text.encode("utf-16-le") + b"\0\0"
    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    pointer = kernel32.GlobalLock(handle)
    ctypes.memmove(pointer, data, len(data))
    kernel32.GlobalUnlock(handle)
    if not _win_open(user32):
        return
    try:
        user32.EmptyClipboard()
        user32.SetClipboardData(CF_UNICODETEXT, handle)  # Windows now owns the memory
    finally:
        user32.CloseClipboard()
