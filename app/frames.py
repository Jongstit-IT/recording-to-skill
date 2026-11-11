"""Pick evidence frames from recorded activity and build the outbox the AI may see."""
import bisect
import shutil
import sys
from pathlib import Path

try:
    import extract_frames as ef
except ImportError:  # running from source
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "recording-to-skill" / "scripts"))
    import extract_frames as ef

from recorder import tool, video_time

MAX_WIDTH = 1600


def plan(events, timing, monitor, duration, cap=40, gap=8.0):
    """Video times worth a frame: just before each click (marked), after window switches, gaps, start/end."""
    items = [{"t": 0.0, "kind": "start"}]
    for e in events:
        t = video_time(e["t"], timing)
        if e.get("own") or t is None:
            continue
        meta = {"title": e.get("title", ""), "app": e.get("app", "")}
        if e["type"] == "click":
            x, y = e["x"] - monitor["left"], e["y"] - monitor["top"]
            if 0 <= x < monitor["width"] and 0 <= y < monitor["height"]:
                items.append({"t": round(max(t - 0.2, 0), 3), "kind": "click", "click": [x, y], **meta})
        elif e["type"] == "focus":
            items.append({"t": round(min(t + 0.8, duration), 3), "kind": "window", **meta})
    items.append({"t": round(duration, 3), "kind": "end"})
    items.sort(key=lambda i: i["t"])

    filled = []
    for a, b in zip(items, items[1:]):
        filled.append(a)
        n = int((b["t"] - a["t"]) // gap)
        filled += [{"t": round(a["t"] + (b["t"] - a["t"]) * k / (n + 1), 3), "kind": "fill"} for k in range(1, n + 1)]
    filled.append(items[-1])

    kept = []
    for item in filled:  # drop near-duplicates, preferring the click frame (it carries the marker)
        if kept and item["t"] - kept[-1]["t"] < 0.3:
            if item["kind"] == "click" and kept[-1]["kind"] != "click":
                kept[-1] = item
            continue
        kept.append(item)
    if len(kept) > cap:  # ponytail: even subsample; smarter scoring (clicks first) if long sessions lose steps
        step = (len(kept) - 1) / (cap - 1)
        kept = [kept[round(i * step)] for i in range(cap)]
    return kept


def extract(session_dir, planned):
    """Write frames/ PNGs for the planned items; returns frame records."""
    video = Path(session_dir) / "video.mp4"
    out = Path(session_dir) / "frames"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir()
    info = ef.probe(tool("ffprobe"), video)
    times, width = info["times"], (MAX_WIDTH if info["width"] > MAX_WIDTH else None)
    frames, used = [], set()
    for item in planned:
        actual = times[max(bisect.bisect_right(times, item["t"] + 1e-6) - 1, 0)]
        if actual in used and item["kind"] != "click":
            continue
        used.add(actual)
        name = f"{len(frames) + 1:03d}_{actual:07.2f}s.png"
        marker = None
        if item.get("click"):
            x, y = item["click"]
            marker = f"drawbox=x={x - 22}:y={y - 22}:w=44:h=44:color=red@0.9:t=4"
        ef.extract(tool("ffmpeg"), video, info["stream"], actual, out / name, width, marker)
        frames.append({"file": name, "t": round(actual, 2), "kind": item["kind"], "title": item.get("title", ""),
                       "app": item.get("app", ""), "excluded": False})
    return frames


def timeline(events, timing, frames):
    """Timeline lines the AI may see: only events whose nearest frame was approved."""
    times = [f["t"] for f in frames]
    lines = []
    for e in events:
        t = video_time(e["t"], timing)
        if e.get("own") or t is None or not frames:
            continue
        i = bisect.bisect_left(times, t)
        nearest = min((j for j in (i - 1, i) if 0 <= j < len(frames)), key=lambda j: abs(times[j] - t))
        if frames[nearest]["excluded"]:
            continue
        where = f"[{e.get('app', '')}] {e.get('title', '')}".strip()
        if e["type"] == "click":
            lines.append(f"{t:7.2f}s  {e['button']} click  {where}")
        else:
            lines.append(f"{t:7.2f}s  window   {where}")
    return lines


def build_outbox(session_dir, frames, events, timing):
    """Fresh outbox/ with only approved frames + timeline.txt. Returns the frame names sent."""
    outbox = Path(session_dir) / "outbox"
    if outbox.exists():
        shutil.rmtree(outbox)
    outbox.mkdir()
    names = []
    for f in frames:
        if not f["excluded"]:
            shutil.copy2(Path(session_dir) / "frames" / f["file"], outbox / f["file"])
            names.append(f["file"])
    (outbox / "timeline.txt").write_text("\n".join(timeline(events, timing, frames)) + "\n", encoding="utf-8")
    return names
