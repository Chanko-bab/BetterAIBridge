"""从摄像头抓一帧，存成 BMP。

用 1995 年就有的 VFW（`avicap32`），因为它是 Windows 自带、又不需要 COM 的那一条路。
它的臭脾气：有的机器上 `capCreateCaptureWindowW` 或 `DRIVER_CONNECT` 会卡住几十秒。
所以**这个文件永远是被 `senses.py` 另起进程跑的**，卡住了就整条杀掉，不牵连模组本身。

    python camgrab.py --list
    python camgrab.py --grab 0 C:\\Temp\\x.bmp 1280 720

输出最后一行是 JSON。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import sys
import time

WM_USER = 0x0400
WM_CAP_DRIVER_CONNECT = WM_USER + 10
WM_CAP_DRIVER_DISCONNECT = WM_USER + 11
WM_CAP_DRIVER_GET_NAME = WM_USER + 12
WM_CAP_SET_PREVIEW = WM_USER + 50
WM_CAP_SET_PREVIEWRATE = WM_USER + 52
WM_CAP_SET_SCALE = WM_USER + 53
WM_CAP_GRAB_FRAME_NOSTOP = WM_USER + 61
WM_CAP_FILE_SAVEDIB = WM_USER + 25
WM_CAP_GET_STATUS = WM_USER + 55
WS_POPUP = 0x80000000

user32 = ctypes.WinDLL("user32", use_last_error=True)
cap = ctypes.WinDLL("avicap32", use_last_error=True)

cap.capCreateCaptureWindowW.restype = wt.HWND
cap.capCreateCaptureWindowW.argtypes = [wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int, wt.HWND, ctypes.c_int]
cap.capGetDriverDescriptionW.restype = wt.BOOL
cap.capGetDriverDescriptionW.argtypes = [wt.WORD, wt.LPWSTR, ctypes.c_int, wt.LPWSTR, ctypes.c_int]

# 64 位上 SendMessageW 的第 4 个参数是 LPARAM（指针宽）；不声明 argtypes 会被当成 int，
# 传 buffer 地址时直接 OverflowError「int too long to convert」。
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.SendMessageW.argtypes = [wt.HWND, wt.UINT, ctypes.c_size_t, ctypes.c_ssize_t]


def emit(obj: dict) -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def list_cameras() -> None:
    found = []
    for i in range(10):
        name = ctypes.create_unicode_buffer(256)
        ver = ctypes.create_unicode_buffer(256)
        if cap.capGetDriverDescriptionW(i, name, 256, ver, 256):
            found.append(name.value.strip() or f"第 {i} 个摄像头")
    emit({"ok": True, "cameras": found})


def grab(index: int, out_path: str, width: int, height: int) -> int:
    hwnd = cap.capCreateCaptureWindowW("bab-sense-cam", WS_POPUP, 0, 0, int(width), int(height), None, 0)
    if not hwnd:
        emit({"ok": False, "error": f"建不起取像窗口（错误 {ctypes.get_last_error()}）"})
        return 3
    try:
        if not user32.SendMessageW(hwnd, WM_CAP_DRIVER_CONNECT, int(index), 0):
            emit({"ok": False, "error": f"连不上第 {index} 个摄像头（没有设备或没权限）"})
            return 4
        try:
            buf = ctypes.create_unicode_buffer(256)
            user32.SendMessageW(hwnd, WM_CAP_DRIVER_GET_NAME, 0, ctypes.cast(buf, ctypes.c_void_p).value)
            name = buf.value.strip()
            user32.SendMessageW(hwnd, WM_CAP_SET_PREVIEW, 0, 0)      # 别在屏幕上闪一个预览窗
            user32.SendMessageW(hwnd, WM_CAP_SET_SCALE, 1, 0)
            user32.SendMessageW(hwnd, WM_CAP_SET_PREVIEWRATE, 30, 0)
            got = False
            for _ in range(14):                                      # 摄像头要热身，多试几次
                if user32.SendMessageW(hwnd, WM_CAP_GRAB_FRAME_NOSTOP, 0, 0):
                    status = ctypes.create_string_buffer(64)
                    user32.SendMessageW(hwnd, WM_CAP_GET_STATUS, 0, ctypes.cast(status, ctypes.c_void_p).value)
                    path_buf = ctypes.create_unicode_buffer(str(out_path), 260)
                    if user32.SendMessageW(hwnd, WM_CAP_FILE_SAVEDIB, 0,
                                           ctypes.cast(path_buf, ctypes.c_void_p).value):
                        got = True
                        break
                time.sleep(0.18)
            if not got or not os.path.isfile(out_path):
                emit({"ok": False, "error": f"摄像头 {name or index} 连上了但存不出画面"})
                return 5
            emit({"ok": True, "path": out_path, "camera": name, "bytes": os.path.getsize(out_path)})
            return 0
        finally:
            user32.SendMessageW(hwnd, WM_CAP_DRIVER_DISCONNECT, 0, 0)
    finally:
        user32.DestroyWindow(hwnd)


def main(argv: list) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        emit({"ok": False, "error": "用法：camgrab.py --list | --grab <序号> <输出.bmp> [宽 高]"})
        return 2
    if argv[0] == "--list":
        list_cameras()
        return 0
    if argv[0] == "--grab":
        if len(argv) < 3:
            emit({"ok": False, "error": "--grab 要三个参数：序号、输出路径"})
            return 2
        w = int(argv[3]) if len(argv) > 3 and argv[3].isdigit() else 1280
        h = int(argv[4]) if len(argv) > 4 and argv[4].isdigit() else 720
        return grab(int(argv[1]) if argv[1].isdigit() else 0, argv[2], w, h)
    emit({"ok": False, "error": f"不认识的参数：{argv[0]}"})
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
