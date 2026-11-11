"""Colored frame around the monitor being recorded: click-through, never focused, kept out of the capture."""
import ctypes
import threading
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32")
kernel32 = ctypes.WinDLL("kernel32")

RED, AMBER = 0x2530D9, 0x00A5F2  # COLORREF is 0x00BBGGRR
THICK = 6
WS_POPUP = 0x80000000
# topmost | toolwindow (no taskbar button) | layered + transparent (clicks pass through) | noactivate
EX_STYLE = 0x8 | 0x80 | 0x80000 | 0x20 | 0x08000000
WDA_EXCLUDEFROMCAPTURE = 0x11  # Windows 10 2004+; older Windows shows the frame in the video
WM_QUIT = 0x0012


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", ctypes.c_void_p), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                   wintypes.HINSTANCE, wintypes.LPVOID]
user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF, wintypes.BYTE, wintypes.DWORD]
user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
kernel32.GetModuleHandleW.restype = wintypes.HMODULE


class Border:
    """show(monitor, color) replaces any frame already shown; hide() removes it. Safe to call from any thread."""

    def __init__(self):
        self._thread = None
        self._tid = 0
        self._lock = threading.Lock()
        self._timer = None

    def show(self, monitor, color=RED, seconds=None):
        with self._lock:
            self._hide()
            ready = threading.Event()
            self._thread = threading.Thread(target=self._loop, args=(monitor, color, ready), daemon=True)
            self._thread.start()
            ready.wait(2)
            if seconds:
                self._timer = threading.Timer(seconds, self._expire, args=(self._thread,))
                self._timer.daemon = True
                self._timer.start()

    def hide(self):
        with self._lock:
            self._hide()

    def _expire(self, thread):
        with self._lock:
            if self._thread is thread:  # a newer show() (e.g. recording started) keeps its frame
                self._hide()

    def _hide(self):
        if self._timer:
            self._timer.cancel()
            self._timer = None
        if self._thread and self._thread.is_alive():
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
            self._thread.join(2)
        self._thread = None

    def _loop(self, m, color, ready):
        """Four strips owned by this thread; they are destroyed when the thread's message loop ends."""
        self._tid = kernel32.GetCurrentThreadId()
        hinst = kernel32.GetModuleHandleW(None)
        name = f"RecordingToSkillBorder{color:06x}"
        wc = WNDCLASSW(lpfnWndProc=ctypes.cast(user32.DefWindowProcW, ctypes.c_void_p).value, hInstance=hinst,
                       hbrBackground=gdi32.CreateSolidBrush(color), lpszClassName=name)
        user32.RegisterClassW(ctypes.byref(wc))  # fails harmlessly if already registered
        l, t, w, h = m["left"], m["top"], m["width"], m["height"]
        for x, y, cw, ch in ((l, t, w, THICK), (l, t + h - THICK, w, THICK), (l, t, THICK, h), (l + w - THICK, t, THICK, h)):
            hwnd = user32.CreateWindowExW(EX_STYLE, name, "", WS_POPUP, x, y, cw, ch, None, None, hinst, None)
            user32.SetLayeredWindowAttributes(hwnd, 0, 255, 2)  # LWA_ALPHA: layered windows stay invisible without it
            user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
            user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
        ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.DispatchMessageW(ctypes.byref(msg))
