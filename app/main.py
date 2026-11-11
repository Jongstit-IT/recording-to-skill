"""Recording to Skill: record the screen, review AI-drafted steps, export SKILL.md."""
import base64
import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import activity
import frames
import prompts
import providers
import recorder
import render
import session

APP_NAME = "Recording to Skill"
MAX_SECONDS = 15 * 60
LOG_DIR = session.ROOT.parent
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(filename=LOG_DIR / "app.log", level=logging.INFO, encoding="utf-8",
                    format="%(asctime)s %(levelname)s %(message)s")
if sys.stdout is None or sys.stderr is None:  # --noconsole: library prints must not crash the JS bridge
    sys.stdout = sys.stderr = open(LOG_DIR / "console.log", "a", encoding="utf-8")

import webview  # noqa: E402  (after stdout fix)


def ui_path():
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return str(base / "ui" / "index.html")


class Api:
    def __init__(self):
        self._window = None
        self._rec = None
        self._current = None  # Session being recorded
        self._paused = False
        self._started = 0.0
        self._jobs = {}  # session id -> cancel Event
        self._monitors = recorder.monitors()
        self._act = activity.Activity(hotkeys={
            (activity.MOD_CONTROL | activity.MOD_ALT, ord("R")): self._hotkey_toggle,
            (activity.MOD_CONTROL | activity.MOD_ALT, ord("P")): self.toggle_pause,
        })

    # ---- helpers -----------------------------------------------------------
    def _push(self, kind, **payload):
        if self._window:
            self._window.evaluate_js(f"window.onBackend({json.dumps({'kind': kind, **payload}, ensure_ascii=False)})")

    def _session(self, sid):
        return session.Session(session.ROOT / sid)

    def _view(self, s):
        d = dict(s.data)
        d["summary"] = s.summary()
        if d.get("frames"):
            d["timeline_preview"] = frames.timeline(s.events(), d["timing"], d["frames"])
        return d

    # ---- home --------------------------------------------------------------
    def init(self):
        return {"monitors": [m["label"] for m in self._monitors], "providers": providers.detect(),
                "sessions": session.list_sessions(), "recording": bool(self._rec), "max_seconds": MAX_SECONDS}

    def list_sessions(self):
        return session.list_sessions()

    def get_session(self, sid):
        return self._view(self._session(sid))

    def frame_image(self, sid, name):
        data = (session.ROOT / sid / "frames" / Path(name).name).read_bytes()
        return "data:image/png;base64," + base64.b64encode(data).decode()

    # ---- recording ---------------------------------------------------------
    def start_recording(self, monitor_index, provider, lang):
        if self._rec:
            return {"error": "กำลังอัดอยู่แล้ว"}
        mon = self._monitors[int(monitor_index)]
        self._current = session.Session.create(provider=provider, lang=lang, monitor=mon)
        self._rec = recorder.Recorder(self._current.dir, mon)
        self._act.start(self._current.dir / "events.jsonl")
        self._rec.start()
        self._paused, self._started = False, time.time()
        threading.Thread(target=self._limit, args=(self._rec,), daemon=True).start()
        if self._window:
            self._window.minimize()
        return {"id": self._current.data["id"]}

    def _limit(self, rec):
        while self._rec is rec:
            if time.time() - self._started > MAX_SECONDS:
                self._push("status", text="ครบ 15 นาที หยุดอัดอัตโนมัติ")
                self._hotkey_toggle()
                return
            time.sleep(1)

    def toggle_pause(self):
        if not self._rec:
            return {"paused": False}
        if self._paused:
            self._rec.start()
        else:
            self._rec.pause()
        self._paused = not self._paused
        self._push("paused", paused=self._paused)
        return {"paused": self._paused}

    def stop_recording(self):
        if not self._rec:
            return {"error": "ไม่ได้อัดอยู่"}
        rec, s = self._rec, self._current
        self._rec = None
        self._act.stop()
        if self._window:
            self._window.restore()
        try:
            timing = rec.stop()
            duration = sum(t["duration"] for t in timing)
            planned = frames.plan(s.events(), timing, s.data["monitor"], duration)
            recs = frames.extract(s.dir, planned)
            s.update(status="recorded", timing=timing, frames=recs)
        except Exception as e:  # keep the session so the user can delete it
            logging.exception("stop failed")
            s.update(status="failed", error=str(e))
            return {"error": f"บันทึกไม่สำเร็จ: {e}", "id": s.data["id"]}
        return self._view(s)

    def _hotkey_toggle(self):
        if self._rec:
            self._push("stopping")
            self._push("stopped", session=self.stop_recording())
        else:
            self._push("hotkey_start")

    # ---- review + analysis ---------------------------------------------------
    def update(self, sid, fields):
        allowed = {"goal", "provider", "lang", "analysis", "skill", "frames"}
        s = self._session(sid)
        s.update(**{k: v for k, v in fields.items() if k in allowed})
        return {"timeline_preview": frames.timeline(s.events(), s.data["timing"], s.data["frames"])}

    def analyze(self, sid):
        s = self._session(sid)
        sent = frames.build_outbox(s.dir, s.data["frames"], s.events(), s.data["timing"])
        if not sent:
            return {"error": "ไม่มีภาพที่จะส่ง เลือกอย่างน้อย 1 ภาพ"}
        prompt = prompts.analysis_prompt(s.data["goal"], sent, s.data["lang"])
        self._run(s, "analysis", prompt, prompts.ANALYSIS_SCHEMA, sent, "analyzed")
        return {"started": True, "frames": len(sent)}

    def create_skill(self, sid):
        s = self._session(sid)
        prompt = prompts.skill_prompt(s.data["goal"], s.data["analysis"], s.data["lang"])
        outbox = s.dir / "outbox"
        outbox.mkdir(exist_ok=True)
        self._run(s, "skill", prompt, prompts.SKILL_SCHEMA, [], "skill_draft")
        return {"started": True}

    def _run(self, s, field, prompt, schema, images, status):
        cancel = threading.Event()
        sid = s.data["id"]
        self._jobs[sid] = cancel

        def work():
            try:
                result = providers.run(s.data["provider"], prompt, schema, str(s.dir / "outbox"), images,
                                       on_progress=lambda n, secs: self._push("progress", id=sid, lines=n, secs=secs),
                                       cancel=cancel)
                s.update(**{field: result, "status": status})
                self._push("done", id=sid, session=self._view(s))
            except Exception as e:
                logging.exception("AI run failed")
                self._push("failed", id=sid, error=str(e))
            finally:
                self._jobs.pop(sid, None)

        threading.Thread(target=work, daemon=True).start()

    def cancel(self, sid):
        if sid in self._jobs:
            self._jobs[sid].set()

    # ---- export ------------------------------------------------------------
    def export(self, sid):
        s = self._session(sid)
        downloads = str(Path.home() / "Downloads")
        picked = self._window.create_file_dialog(webview.FileDialog.FOLDER, directory=downloads)
        if not picked:
            return {"cancelled": True}
        folder = picked[0] if isinstance(picked, (list, tuple)) else picked
        try:
            target = render.export(s.data, folder)
        except FileExistsError as e:
            return {"error": str(e)}
        s.update(status="skill", exported=str(target))
        return {"path": str(target)}

    def reveal(self, path):
        subprocess.Popen(["explorer", "/select,", str(Path(path) / "SKILL.md")])

    def delete_session(self, sid):
        session.delete(sid)
        return session.list_sessions()


def main():
    activity.set_dpi_aware()
    api = Api()
    api._window = webview.create_window(APP_NAME, ui_path(), js_api=api, width=1280, height=820, min_size=(980, 640))
    webview.start(debug=bool(os.environ.get("RTS_DEBUG")))


if __name__ == "__main__":
    main()
