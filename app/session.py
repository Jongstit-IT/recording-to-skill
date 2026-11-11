"""A recording session on disk: video, events, frames and session.json (autosaved)."""
import json
import os
import shutil
import time
from pathlib import Path

ROOT = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "RecordingToSkill" / "sessions"


class Session:
    def __init__(self, folder):
        self.dir = Path(folder)
        self.file = self.dir / "session.json"
        self.data = json.loads(self.file.read_text(encoding="utf-8")) if self.file.exists() else {}

    @classmethod
    def create(cls, root=ROOT, **fields):
        sid = time.strftime("%Y%m%d-%H%M%S")
        folder = Path(root) / sid
        n = 1
        while folder.exists():
            n += 1
            folder = Path(root) / f"{sid}-{n}"
        folder.mkdir(parents=True)
        s = cls(folder)
        s.data = {"id": folder.name, "created": time.time(), "status": "recording", "goal": "", "provider": "claude",
                  "lang": "th", "timing": [], "frames": [], "analysis": None, "skill": None, **fields}
        s.save()
        return s

    def save(self):
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.file)

    def update(self, **fields):
        self.data.update(fields)
        self.save()
        return self.data

    def events(self):
        path = self.dir / "events.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def summary(self):
        d = self.data
        video = self.dir / "video.mp4"
        return {"id": d["id"], "created": d["created"], "status": d["status"],
                "title": (d.get("analysis") or {}).get("task_title") or "ยังไม่ได้วิเคราะห์",
                "duration": sum(s["duration"] for s in d.get("timing", [])),
                "size_mb": round(video.stat().st_size / 1e6, 1) if video.exists() else 0,
                "steps": len((d.get("analysis") or {}).get("steps", []))}


def list_sessions(root=ROOT):
    root = Path(root)
    if not root.exists():
        return []
    found = [Session(p) for p in root.iterdir() if (p / "session.json").exists()]
    return sorted((s.summary() for s in found), key=lambda s: s["created"], reverse=True)


def delete(session_id, root=ROOT):
    folder = (Path(root) / session_id).resolve()
    if folder.parent != Path(root).resolve():
        raise ValueError("invalid session id")
    shutil.rmtree(folder)
