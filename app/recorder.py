"""Screen recording with FFmpeg gdigrab.

-copyts keeps gdigrab's wall-clock (epoch) timestamps, so mouse events from
activity.py (time.time()) line up with video frames without guessing latency.
Pause = stop the current segment; resume = start a new one; stop = concat to video.mp4.
"""
import ctypes
import os
import shutil
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000
FPS = 10
MAX_SECONDS = 15 * 60


class _IO(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulonglong) for n in ("r", "w", "o", "rb", "wb", "ob")]


class _BASIC(ctypes.Structure):
    _fields_ = [("a", ctypes.c_longlong), ("b", ctypes.c_longlong), ("LimitFlags", wintypes.DWORD),
                ("c", ctypes.c_size_t), ("d", ctypes.c_size_t), ("e", wintypes.DWORD), ("f", ctypes.c_size_t),
                ("g", wintypes.DWORD), ("h", wintypes.DWORD)]


class _EXTENDED(ctypes.Structure):
    _fields_ = [("Basic", _BASIC), ("Io", _IO), ("p", ctypes.c_size_t), ("j", ctypes.c_size_t),
                ("pp", ctypes.c_size_t), ("jp", ctypes.c_size_t)]


_job = None


def die_with_app(proc):
    """Child processes (ffmpeg, AI CLIs) are killed when this app exits, even on a crash or Task Manager kill."""
    global _job
    k = ctypes.windll.kernel32
    if _job is None:
        k.CreateJobObjectW.restype = wintypes.HANDLE
        _job = k.CreateJobObjectW(None, None)
        info = _EXTENDED()
        info.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        k.SetInformationJobObject(wintypes.HANDLE(_job), 9, ctypes.byref(info), ctypes.sizeof(info))
    k.AssignProcessToJobObject(wintypes.HANDLE(_job), wintypes.HANDLE(int(proc._handle)))


def tool(name):
    """Bundled ffmpeg/ffprobe when frozen by PyInstaller, else from PATH."""
    if getattr(sys, "frozen", False):
        bundled = Path(sys._MEIPASS) / "ffmpeg" / f"{name}.exe"
        if bundled.exists():
            return str(bundled)
    return shutil.which(name)


class _MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR * 32)]


def monitors():
    """Physical-pixel monitor rectangles (call activity.set_dpi_aware() first). Primary first."""
    found = []
    proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def callback(handle, hdc, rect, lparam):
        info = _MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(info)
        ctypes.windll.user32.GetMonitorInfoW(handle, ctypes.byref(info))
        r = info.rcMonitor
        found.append({"left": r.left, "top": r.top, "width": r.right - r.left, "height": r.bottom - r.top,
                      "primary": bool(info.dwFlags & 1)})
        return True

    ctypes.windll.user32.EnumDisplayMonitors(None, None, proc_type(callback), 0)
    found.sort(key=lambda m: (not m["primary"], m["left"], m["top"]))
    for i, m in enumerate(found, 1):
        m["label"] = f"จอ {i}{' (หลัก)' if m['primary'] else ''} {m['width']}x{m['height']}"
    return found


class Recorder:
    def __init__(self, folder, monitor):
        self.folder = Path(folder)
        self.monitor = monitor
        self.segments = []  # Path of each .mkv segment
        self.proc = None

    @property
    def recording(self):
        return self.proc is not None

    def start(self):
        if self.proc:
            return
        m = self.monitor
        seg = self.folder / f"seg_{len(self.segments):03d}.mkv"
        cmd = [tool("ffmpeg"), "-hide_banner", "-v", "error", "-y", "-copyts",
               "-f", "gdigrab", "-framerate", str(FPS), "-draw_mouse", "1",
               "-offset_x", str(m["left"]), "-offset_y", str(m["top"]),
               "-video_size", f"{m['width']}x{m['height']}", "-i", "desktop",
               "-frames:v", str(MAX_SECONDS * FPS),  # hard cap even if the app never says stop
               "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-g", str(FPS * 2),  # keyframe every 2 s: fast seeks
               "-pix_fmt", "yuv420p", str(seg)]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE,
                                     creationflags=CREATE_NO_WINDOW)
        die_with_app(self.proc)
        self.segments.append(seg)

    def pause(self):
        if not self.proc:
            return
        proc, self.proc = self.proc, None
        try:
            _, err = proc.communicate(b"q", timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            _, err = proc.communicate()
        self.errors = (err or b"").decode("utf-8", "replace").strip()[-300:]

    def stop(self):
        """Finish recording; returns segment timing [{start_epoch, offset, duration}] and writes video.mp4."""
        self.pause()
        timing, offset = [], 0.0
        good = []
        for seg in self.segments:
            info = probe_segment(seg)
            if not info:
                continue
            start, duration = info
            timing.append({"start_epoch": start, "offset": round(offset, 3), "duration": round(duration, 3)})
            offset += duration
            good.append(seg)
        if not good:
            raise RuntimeError("ไม่มีภาพที่อัดได้ " + getattr(self, "errors", ""))
        listing = self.folder / "segments.txt"
        listing.write_text("".join(f"file '{s.name}'\n" for s in good), encoding="utf-8")
        p = subprocess.run([tool("ffmpeg"), "-hide_banner", "-v", "error", "-y", "-f", "concat", "-safe", "0",
                            "-i", listing.name, "-c", "copy", "-movflags", "+faststart", "video.mp4"],
                           cwd=self.folder, capture_output=True, encoding="utf-8", errors="replace",
                           creationflags=CREATE_NO_WINDOW, timeout=300)
        if p.returncode != 0:
            raise RuntimeError("รวมวิดีโอไม่สำเร็จ: " + p.stderr[-300:])
        for seg in good:
            seg.unlink()
        listing.unlink()
        return timing


def probe_segment(path):
    """(start_epoch, duration) from frame timestamps of a -copyts segment, or None if empty."""
    if not path.exists() or path.stat().st_size == 0:
        return None
    p = subprocess.run([tool("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time",
                        "-of", "csv=p=0", str(path)], capture_output=True, encoding="utf-8", errors="replace",
                       creationflags=CREATE_NO_WINDOW, timeout=120)
    times = sorted(float(x.split(",")[0]) for x in p.stdout.split() if x.split(",")[0] not in ("", "N/A"))
    if not times:
        return None
    return times[0], times[-1] - times[0] + 1 / FPS


def video_time(epoch, timing):
    """Map a wall-clock event time to seconds in video.mp4; None if it fell in a pause."""
    for seg in timing:
        if seg["start_epoch"] <= epoch < seg["start_epoch"] + seg["duration"]:
            return round(seg["offset"] + epoch - seg["start_epoch"], 3)
    return None


if os.name != "nt":  # pragma: no cover
    raise ImportError("recorder.py supports Windows only")
