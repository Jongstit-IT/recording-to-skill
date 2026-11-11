"""Windows activity capture: mouse clicks, foreground-window changes, global hotkeys.

Keystrokes are never recorded. One native thread owns the message loop for the
low-level mouse hook and RegisterHotKey; a second thread polls the foreground window.
Times are wall-clock epoch seconds (time.time()), the same clock gdigrab -copyts uses.
"""
import ctypes
import json
import os
import queue
import threading
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WH_MOUSE_LL = 14
WM_QUIT, WM_HOTKEY, WM_APP = 0x0012, 0x0312, 0x8000
CLICKS = {0x0201: "left", 0x0204: "right", 0x0207: "middle"}
MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x1, 0x2, 0x4000
INSTALL, UNINSTALL = WM_APP + 1, WM_APP + 2
LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.CallNextHookEx.restype = LRESULT
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.GetForegroundWindow.restype = wintypes.HWND
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.OpenProcess.restype = wintypes.HANDLE


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", wintypes.POINT), ("mouseData", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


def set_dpi_aware():
    """Physical-pixel coordinates everywhere (must run before any window is created)."""
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # per-monitor aware v2
    except (AttributeError, OSError):
        pass


def window_info(hwnd):
    """(title, exe name, pid) of a top-level window; empty strings if unavailable."""
    if not hwnd:
        return "", "", 0
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    exe = ""
    handle = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if handle:
        size = wintypes.DWORD(1024)
        path = ctypes.create_unicode_buffer(1024)
        if kernel32.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
            exe = os.path.basename(path.value)
        kernel32.CloseHandle(handle)
    return buf.value, exe, pid.value


class Activity:
    """Start once per app. `hotkeys` maps (modifiers, vk) -> callback run on a worker thread."""

    def __init__(self, hotkeys=None):
        self.hotkeys = hotkeys or {}
        self._sink = None  # file object while recording
        self._lock = threading.Lock()
        self._clicks = queue.Queue()
        self._tid = None
        self._hook = None
        self._proc = HOOKPROC(self._on_mouse)  # keep a reference: ctypes callbacks must outlive the hook
        ready = threading.Event()
        threading.Thread(target=self._loop, args=(ready,), daemon=True, name="activity-hook").start()
        threading.Thread(target=self._resolve_clicks, daemon=True, name="activity-clicks").start()
        threading.Thread(target=self._poll_focus, daemon=True, name="activity-focus").start()
        ready.wait(5)

    # ---- recording control -------------------------------------------------
    def start(self, events_path):
        with self._lock:
            self._sink = open(events_path, "a", encoding="utf-8")
            self._last_focus = None
        user32.PostThreadMessageW(self._tid, INSTALL, 0, 0)

    def stop(self):
        user32.PostThreadMessageW(self._tid, UNINSTALL, 0, 0)
        time.sleep(0.3)  # let queued clicks resolve
        with self._lock:
            if self._sink:
                self._sink.close()
            self._sink = None

    def _write(self, event):
        with self._lock:
            if self._sink:
                self._sink.write(json.dumps(event, ensure_ascii=False) + "\n")
                self._sink.flush()

    # ---- native thread -----------------------------------------------------
    def _loop(self, ready):
        self._tid = kernel32.GetCurrentThreadId()
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)  # create the thread's message queue
        ids = {}
        for i, (mods, vk) in enumerate(self.hotkeys, 1):
            if user32.RegisterHotKey(None, i, mods | MOD_NOREPEAT, vk):
                ids[i] = self.hotkeys[(mods, vk)]
        ready.set()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam in ids:
                threading.Thread(target=ids[msg.wParam], daemon=True).start()
            elif msg.message == INSTALL and not self._hook:
                self._hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._proc, kernel32.GetModuleHandleW(None), 0)
            elif msg.message == UNINSTALL and self._hook:
                user32.UnhookWindowsHookEx(self._hook)
                self._hook = None

    def _on_mouse(self, code, wparam, lparam):
        if code == 0 and wparam in CLICKS:
            info = ctypes.cast(lparam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            self._clicks.put((time.time(), CLICKS[wparam], info.pt.x, info.pt.y))  # keep the hook fast
        return user32.CallNextHookEx(None, code, wparam, lparam)

    # ---- worker threads ----------------------------------------------------
    def _resolve_clicks(self):
        while True:
            t, button, x, y = self._clicks.get()
            hwnd = user32.GetAncestor(user32.WindowFromPoint(wintypes.POINT(x, y)), 2)  # GA_ROOT
            title, exe, pid = window_info(hwnd)
            self._write({"t": round(t, 3), "type": "click", "button": button, "x": x, "y": y,
                         "title": title, "app": exe, "own": pid == os.getpid()})

    def _poll_focus(self):
        while True:
            time.sleep(0.25)
            if not self._sink:
                continue
            title, exe, pid = window_info(user32.GetForegroundWindow())
            if (title, exe) != self._last_focus:
                self._last_focus = (title, exe)
                self._write({"t": round(time.time(), 3), "type": "focus", "title": title, "app": exe,
                             "own": pid == os.getpid()})
