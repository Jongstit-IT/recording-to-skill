"""Tests for the GUI app's non-UI logic. Run: python tests/test_app.py"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import frames  # noqa: E402
import prompts  # noqa: E402
import providers  # noqa: E402
import render  # noqa: E402
import session  # noqa: E402
from recorder import video_time  # noqa: E402

MON = {"left": 1920, "top": 0, "width": 1280, "height": 720}
TIMING = [{"start_epoch": 1000.0, "offset": 0.0, "duration": 10.0},   # pause from 1010 to 1020
          {"start_epoch": 1020.0, "offset": 10.0, "duration": 10.0}]


def rgb_at(png, x, y):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(png), "-vf", f"crop=2:2:{x}:{y}", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return tuple(raw[:3])


def frontmatter(text):
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert m, "no frontmatter"
    out = {}
    for line in m.group(1).splitlines():
        key, value = line.split(": ", 1)
        out[key] = json.loads(value) if value.startswith('"') else value
    return out


class TimingTest(unittest.TestCase):
    def test_video_time_skips_pause(self):
        self.assertEqual(video_time(1005.0, TIMING), 5.0)
        self.assertIsNone(video_time(1015.0, TIMING))  # paused
        self.assertEqual(video_time(1022.5, TIMING), 12.5)
        self.assertIsNone(video_time(999.0, TIMING))

    def test_plan_marks_clicks_and_fills_gaps(self):
        events = [
            {"t": 1002.0, "type": "click", "button": "left", "x": 2000, "y": 100, "title": "A", "app": "a.exe"},
            {"t": 1003.0, "type": "click", "button": "left", "x": 100, "y": 100, "title": "other monitor"},
            {"t": 1004.0, "type": "click", "button": "left", "x": 2000, "y": 100, "own": True},
            {"t": 1015.0, "type": "click", "button": "left", "x": 2000, "y": 100},  # during pause
            {"t": 1021.0, "type": "focus", "title": "B", "app": "b.exe"},
        ]
        plan = frames.plan(events, TIMING, MON, duration=20.0)
        clicks = [p for p in plan if p["kind"] == "click"]
        self.assertEqual(len(clicks), 1)
        self.assertEqual(clicks[0]["click"], [80, 100])  # monitor-relative
        self.assertAlmostEqual(clicks[0]["t"], 1.8)
        self.assertIn(11.8, [p["t"] for p in plan if p["kind"] == "window"])
        self.assertEqual(plan[0]["t"], 0.0)
        self.assertEqual(plan[-1]["t"], 20.0)
        times = [p["t"] for p in plan]
        self.assertEqual(times, sorted(times))
        self.assertLessEqual(max(b - a for a, b in zip(times, times[1:])), 8.0)

    def test_plan_cap(self):
        events = [{"t": 1000.0 + i * 0.4, "type": "click", "button": "left", "x": 2000, "y": 10} for i in range(25)]
        plan = frames.plan(events, TIMING, MON, duration=20.0, cap=10)
        self.assertEqual(len(plan), 10)
        self.assertEqual((plan[0]["t"], plan[-1]["t"]), (0.0, 20.0))


class MediaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp()) / "เซสชัน ทดสอบ"
        cls.tmp.mkdir()
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=1920x1080:r=10:d=6",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(cls.tmp / "video.mp4")], check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp.parent, ignore_errors=True)

    def test_extract_marks_click_and_outbox_hides_excluded(self):
        mon = {"left": 0, "top": 0, "width": 1920, "height": 1080}
        timing = [{"start_epoch": 1000.0, "offset": 0.0, "duration": 6.0}]
        events = [{"t": 1002.0, "type": "click", "button": "left", "x": 960, "y": 540, "title": "ลับ", "app": "x.exe"},
                  {"t": 1004.5, "type": "focus", "title": "เปิดเผยได้", "app": "y.exe"}]
        plan = frames.plan(events, timing, mon, duration=6.0)
        recs = frames.extract(self.tmp, plan)
        click = next(r for r in recs if r["kind"] == "click")
        png = self.tmp / "frames" / click["file"]
        # 1920 wide -> scaled to 1600 (ratio 0.8333); marker edge at x=960-22 -> ~782
        r, g, b = rgb_at(png, round((960 - 22) * 1600 / 1920), round(540 * 1600 / 1920))
        self.assertGreater(r, 150)
        self.assertLess(b, 120)
        self.assertGreater(rgb_at(png, 10, 10)[2], 200)  # background stays blue

        click["excluded"] = True
        sent = frames.build_outbox(self.tmp, recs, events, timing)
        outbox = self.tmp / "outbox"
        self.assertNotIn(click["file"], sent)
        self.assertFalse((outbox / click["file"]).exists())
        self.assertEqual(sorted(p.name for p in outbox.glob("*.png")), sorted(sent))
        tl = (outbox / "timeline.txt").read_text(encoding="utf-8")
        self.assertNotIn("ลับ", tl)
        self.assertIn("เปิดเผยได้", tl)


SKILL = {"name": "Monthly Sales: Summary!", "description": "สรุปยอดขาย: รายเดือน. Use when <user> asks # report",
         "inputs": [{"name": "sales_folder", "description": "โฟลเดอร์ไฟล์", "how_to_get": "ถามผู้ใช้"}],
         "prerequisites": ["Python 3"], "steps": [{"title": "อ่านไฟล์ทั้งหมด", "detail": "วนทุกไฟล์", "tool": "Python"}],
         "output": "summary.csv", "errors": ["ไม่มีไฟล์: หยุดและแจ้ง"], "assumptions": []}


class RenderTest(unittest.TestCase):
    def test_skill_frontmatter_is_valid(self):
        text = render.skill_md(SKILL, "th")
        fm = frontmatter(text)
        self.assertEqual(set(fm), {"name", "description"})
        self.assertEqual(fm["name"], "monthly-sales-summary")
        self.assertNotIn("<", fm["description"])
        self.assertIn("สรุปยอดขาย", fm["description"])
        self.assertEqual(render.skill_name("recording-to-skill"), "recorded-task")
        self.assertEqual(render.skill_name("งานไทยล้วน"), "recorded-task")

    def test_export_refuses_overwrite(self):
        tmp = Path(tempfile.mkdtemp())
        data = {"id": "x", "provider": "claude", "lang": "en", "goal": "", "timing": [],
                "frames": [{"file": "001.png", "excluded": False}],
                "analysis": {"task_title": "T", "summary": "S", "uncertainties": ["u"],
                             "steps": [{"title": "a|b", "detail": "d", "frames": ["001.png"], "basis": "observed"}]},
                "skill": SKILL}
        target = render.export(data, tmp)
        self.assertTrue((target / "SKILL.md").exists())
        self.assertIn("a\\|b", (target / "analysis.md").read_text(encoding="utf-8"))
        with self.assertRaises(FileExistsError):
            render.export(data, tmp)
        shutil.rmtree(tmp)


class ProviderTest(unittest.TestCase):
    def test_resolve_cmd_shim_to_real_exe(self):
        tmp = Path(tempfile.mkdtemp()) / "npm ทดสอบ"
        (tmp / "node_modules" / "x" / "bin").mkdir(parents=True)
        (tmp / "node_modules" / "x" / "bin" / "faketool.exe").write_bytes(b"")
        (tmp / "faketool.cmd").write_text('@ECHO off\r\n"%dp0%\\node_modules\\x\\bin\\faketool.exe"   %*\r\n')
        old = os.environ["PATH"]
        os.environ["PATH"] = f"{tmp}{os.pathsep}{old}"
        try:
            self.assertEqual(providers.resolve("faketool"), [str(tmp / "node_modules" / "x" / "bin" / "faketool.exe")])
        finally:
            os.environ["PATH"] = old
            shutil.rmtree(tmp.parent)

    def test_commands_keep_prompt_off_argv(self):
        tmp = Path(tempfile.mkdtemp()) / "outbox ไทย"
        tmp.mkdir()
        patcher = mock.patch.object(providers, "resolve", lambda name: [f"C:\\bin\\{name}.exe"])
        patcher.start()
        self.addCleanup(patcher.stop)
        argv, out = providers.build_command("claude", prompts.ANALYSIS_SCHEMA, tmp, ["001_00001.00s.png"])
        self.assertIn("--safe-mode", argv)
        self.assertNotIn("--bare", argv)
        self.assertEqual(argv[argv.index("--tools") + 1], "Read")
        self.assertIsNone(out)
        argv, out = providers.build_command("codex", prompts.ANALYSIS_SCHEMA, tmp, ["a.png", "b.png"])
        self.assertEqual(argv[-1], "-")
        self.assertIn("--image=a.png,b.png", argv)
        self.assertTrue((tmp / "_schema.json").exists())
        shutil.rmtree(tmp.parent)

    def test_parse_claude_result(self):
        lines = ['{"type":"system"}\n', json.dumps({"type": "result", "is_error": False, "structured_output": {"ok": 1}})]
        self.assertEqual(providers.parse_claude(lines), {"ok": 1})
        with self.assertRaises(providers.ProviderError):
            providers.parse_claude([json.dumps({"type": "result", "is_error": True, "result": "Not logged in"})])

    def test_schemas_are_strict(self):
        def walk(node):
            if node.get("type") == "object":
                self.assertFalse(node["additionalProperties"])
                self.assertEqual(set(node["required"]), set(node["properties"]))
                for child in node["properties"].values():
                    walk(child)
            elif node.get("type") == "array":
                walk(node["items"])
        walk(prompts.ANALYSIS_SCHEMA)
        walk(prompts.SKILL_SCHEMA)


class SessionTest(unittest.TestCase):
    def test_create_save_list_delete(self):
        root = Path(tempfile.mkdtemp()) / "ราก"
        s = session.Session.create(root, goal="ทดสอบ")
        s.update(status="recorded", timing=[{"start_epoch": 1, "offset": 0, "duration": 3.5}])
        again = session.Session(s.dir)
        self.assertEqual(again.data["goal"], "ทดสอบ")
        listed = session.list_sessions(root)
        self.assertEqual(listed[0]["duration"], 3.5)
        with self.assertRaises(ValueError):
            session.delete("..", root)
        session.delete(s.data["id"], root)
        self.assertEqual(session.list_sessions(root), [])
        shutil.rmtree(root.parent)


if __name__ == "__main__":
    unittest.main(verbosity=2)
