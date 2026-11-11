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
import border
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
        self._border = border.Border()
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
    def identify_monitor(self, monitor_index):
        """Flash the frame on the monitor picked in the dropdown."""
        if not self._rec:
            self._border.show(self._monitors[int(monitor_index)], seconds=1.5)

    def start_recording(self, monitor_index, provider, lang):
        if self._rec:
            return {"error": "กำลังอัดอยู่แล้ว"}
        mon = self._monitors[int(monitor_index)]
        self._current = session.Session.create(provider=provider, lang=lang, monitor=mon)
        self._rec = recorder.Recorder(self._current.dir, mon)
        self._act.start(self._current.dir / "events.jsonl")
        self._rec.start()
        self._border.show(mon)
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
        self._border.show(self._current.data["monitor"], border.AMBER if self._paused else border.RED)
        self._push("paused", paused=self._paused)
        return {"paused": self._paused}

    def stop_recording(self):
        if not self._rec:
            return {"error": "ไม่ได้อัดอยู่"}
        rec, s = self._rec, self._current
        self._rec = None
        self._act.stop()
        self._border.hide()
        try:
            timing = rec.stop()  # stop capturing before the app window comes back on screen
            if self._window:
                self._window.restore()
            duration = sum(t["duration"] for t in timing)
            planned = frames.plan(s.events(), timing, s.data["monitor"], duration)
            recs = frames.extract(s.dir, planned, lambda done, total: self._push("extracting", done=done, total=total))
            s.update(status="recorded", timing=timing, frames=recs)
        except Exception as e:  # keep the session so the user can delete it
            logging.exception("stop failed")
            if self._window:
                self._window.restore()
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
        timeline = (s.dir / "outbox" / "timeline.txt").read_text(encoding="utf-8")
        prompt = prompts.analysis_prompt(s.data["goal"], sent, s.data["lang"], timeline)
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
            t0 = time.time()
            try:
                result = providers.run(s.data["provider"], prompt, schema, str(s.dir / "outbox"), images,
                                       on_progress=lambda n, secs: self._push("progress", id=sid, lines=n, secs=secs),
                                       cancel=cancel)
                logging.info("%s %s done in %.0fs (%d images)", s.data["provider"], field, time.time() - t0, len(images))
                fresh = self._session(sid)  # keep edits the user autosaved while the AI was running
                fresh.update(**{field: result, "status": status})
                self._push("done", id=sid, session=self._view(fresh))
            except Exception as e:
                logging.exception("AI run failed")
                self._push("failed", id=sid, error=str(e))
            finally:
                self._jobs.pop(sid, None)

        threading.Thread(target=work, daemon=True).start()

    def cancel(self, sid):
        if sid in self._jobs:
            self._jobs[sid].set()

    def _on_closing(self):
        """Window closed mid-recording or mid-analysis: stop capture and AI, keep the session for deletion."""
        for cancel in self._jobs.values():
            cancel.set()
        if self._rec:
            rec, self._rec = self._rec, None
            self._act.stop()
            self._border.hide()
            rec.pause()
            self._current.update(status="failed", error="ปิดแอประหว่างอัด วิดีโอส่วนนี้ไม่ได้บันทึกเป็นผลลัพธ์ ลบ session นี้ได้")

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
    api._window.events.closing += api._on_closing
    webview.start(debug=bool(os.environ.get("RTS_DEBUG")))
    os._exit(0)  # don't wait on worker threads; the job object takes child processes down with us


if __name__ == "__main__":
    main()
