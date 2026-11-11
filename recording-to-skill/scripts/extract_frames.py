#!/usr/bin/env python3
"""Probe a screen recording and extract PNG frames plus manifest.json.

Default: --max-frames frames spread evenly from the first to the last video frame.
--timestamps "5,12.5,40": frames at chosen seconds, to look closer at a moment.
Each sample is the last real frame shown at or before the target time, so
variable-frame-rate recordings (Snipping Tool) and audio longer than the video
do not shift what you see. Python standard library only; needs ffmpeg + ffprobe.
"""
import argparse
import bisect
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

PROBE_TIMEOUT = 300  # seconds; listing packets of a long recording
FRAME_TIMEOUT = 120  # seconds per extracted frame
SEEK_EPS = 0.001  # seek just before the frame so float rounding never skips it
INSTALL_HINT = (
    "Install FFmpeg (it includes ffprobe), make sure both are on PATH, open a new terminal, then retry:\n"
    "  Windows: winget install --id Gyan.FFmpeg -e\n"
    "  macOS:   brew install ffmpeg\n"
    "  Debian/Ubuntu/WSL: sudo apt install ffmpeg"
)


class Fail(Exception):
    def __init__(self, msg, code=1):
        super().__init__(msg)
        self.code = code


def run(cmd, timeout):
    try:
        return subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        raise Fail(f"{Path(cmd[0]).stem} timed out after {timeout}s")


def brief(stderr, n=3):
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    return " | ".join(lines[-n:]) or "no error output"


def num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def probe(ffprobe, src):
    p = run([ffprobe, "-v", "error", "-show_entries",
             "format=duration,start_time:stream=index,codec_type,codec_name,width,height:stream_disposition=attached_pic",
             "-of", "json", str(src)], PROBE_TIMEOUT)
    if p.returncode != 0:
        raise Fail(f"ffprobe cannot read the input (corrupt or not a media file): {brief(p.stderr)}")
    info = json.loads(p.stdout or "{}")
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not s.get("disposition", {}).get("attached_pic")), None)
    if not video or not video.get("width"):
        raise Fail("the input has no video stream (audio-only or unsupported file)")
    start = num(info.get("format", {}).get("start_time")) or 0.0
    p = run([ffprobe, "-v", "error", "-select_streams", str(video["index"]),
             "-show_entries", "packet=pts_time", "-of", "csv=p=0", str(src)], PROBE_TIMEOUT)
    if p.returncode != 0:
        raise Fail(f"ffprobe cannot list video frames: {brief(p.stderr)}")
    times = sorted({round(t - start, 6) for t in (num(line.split(",")[0]) for line in p.stdout.splitlines())
                    if t is not None})
    if not times:
        raise Fail("the video stream contains no frames")
    duration = num(info.get("format", {}).get("duration")) or times[-1]
    return {
        "duration": duration,
        "times": times,
        "width": int(video["width"]),
        "height": int(video["height"]),
        "codec": video.get("codec_name"),
        "stream": video["index"],
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
    }


def parse_timestamps(text):
    values = []
    for part in text.split(","):
        value = num(part.strip())
        if value is None:
            raise Fail(f"--timestamps must be seconds separated by commas, e.g. \"5,12.5,40\" (bad value: {part.strip()!r})", 2)
        values.append(value)
    return sorted(set(values))


def pick(times, targets):
    """(requested, actual) pairs: the last real frame at or before each target, duplicates dropped."""
    pairs, seen = [], set()
    for t in targets:
        actual = times[max(bisect.bisect_right(times, t + 1e-6) - 1, 0)]
        if actual not in seen:
            seen.add(actual)
            pairs.append((t, actual))
    return pairs


def png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", head[16:24])


def extract(ffmpeg, src, stream, t, dest, width, pre_filter=None):
    """pre_filter: optional FFmpeg filter applied before scaling (e.g. drawbox for a click marker)."""
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-n",
           "-ss", f"{max(t - SEEK_EPS, 0):.6f}", "-i", str(src),
           "-map", f"0:{stream}", "-frames:v", "1", "-update", "1"]
    filters = [f for f in (pre_filter, f"scale={width}:-1" if width else None) if f]
    if filters:
        cmd += ["-vf", ",".join(filters)]
    p = run(cmd + [str(dest)], FRAME_TIMEOUT)
    size = png_size(dest) if dest.is_file() else None
    if p.returncode != 0 or not size:
        raise Fail(f"ffmpeg could not extract a frame at {t:.3f}s: {brief(p.stderr)}")
    return size


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(errors="backslashreplace")  # never crash printing Thai paths to a narrow console
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True, help="video file to read (never modified)")
    ap.add_argument("--output-dir", required=True, help="new or empty folder for the PNGs and manifest.json")
    ap.add_argument("--max-frames", type=int, default=12, help="frames spread over the whole clip, incl. first and last (default 12)")
    ap.add_argument("--timestamps", help='seconds separated by commas, e.g. "5,12.5,40" (replaces even sampling)')
    ap.add_argument("--max-width", type=int, default=1920, help="shrink wider frames to this width, keeping aspect ratio; never enlarges (default 1920)")
    args = ap.parse_args(argv)
    try:
        return run_extraction(args)
    except Fail as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return e.code


def run_extraction(args):
    src = Path(args.input).expanduser()
    if not src.is_file():
        hint = ""
        if os.name != "nt" and re.match(r"^[A-Za-z]:[\\/]", args.input):
            hint = " (this is a Windows path; in WSL convert it first: wslpath -u 'C:\\...')"
        raise Fail(f"input file not found: {args.input}{hint}", 2)
    if args.max_frames < 1 or args.max_width < 16:
        raise Fail("--max-frames must be >= 1 and --max-width >= 16", 2)
    targets = parse_timestamps(args.timestamps) if args.timestamps else None
    missing = [name for name in ("ffmpeg", "ffprobe") if not shutil.which(name)]
    if missing:
        raise Fail(f"{' and '.join(missing)} not found on PATH.\n{INSTALL_HINT}", 2)
    out = Path(args.output_dir).expanduser()
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise Fail(f"output already exists and is not an empty folder: {out} (choose a new --output-dir; nothing was changed)", 2)

    info = probe(shutil.which("ffprobe"), src)
    times, duration = info["times"], info["duration"]
    if targets is not None:
        bad = [t for t in targets if t < 0 or t > max(duration, times[-1]) + 1e-3]
        if bad:
            raise Fail(f"timestamps outside the video (0 to {duration:.3f}s): {', '.join(f'{t:g}' for t in bad)}", 2)
    elif args.max_frames == 1:
        targets = [(times[0] + times[-1]) / 2]
    else:
        n = args.max_frames
        targets = [times[0] + (times[-1] - times[0]) * i / (n - 1) for i in range(n)]
    pairs = pick(times, targets)
    width = args.max_width if info["width"] > args.max_width else None

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".extract_frames-", dir=out.parent))
    try:
        frames, size = [], None
        for i, (requested, t) in enumerate(pairs, 1):
            name = f"frame_{i:03d}_{t:09.3f}s.png"
            size = extract(shutil.which("ffmpeg"), src, info["stream"], t, tmp / name, width)
            frames.append({"file": name, "timestamp_sec": round(t, 3), "requested_sec": round(requested, 3)})
        manifest = {
            "source": str(src.resolve()),
            "duration_sec": round(duration, 3),
            "first_frame_sec": round(times[0], 3),
            "last_frame_sec": round(times[-1], 3),
            "video_frames": len(times),
            "width": info["width"],
            "height": info["height"],
            "codec": info["codec"],
            "has_audio": info["has_audio"],
            "frame_width": size[0],
            "frame_height": size[1],
            "mode": "timestamps" if args.timestamps else "even",
            "frames": frames,
        }
        (tmp / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        if out.exists():
            out.rmdir()
        tmp.replace(out)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise

    print(f"OK: {len(frames)} frames -> {out}")
    print(f"manifest: {out / 'manifest.json'}")
    print(f"video: {duration:.2f}s, {info['width']}x{info['height']} {info['codec']}, "
          f"frames saved at {size[0]}x{size[1]}, audio: {'yes' if info['has_audio'] else 'no'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
