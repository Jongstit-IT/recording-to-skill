"""Media-pipeline tests for recording-to-skill/scripts/extract_frames.py.

Builds synthetic clips with FFmpeg under a temp folder whose name has spaces and Thai.
Run: python tests/test_extract_frames.py
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "recording-to-skill" / "scripts" / "extract_frames.py"
FONT = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "arial.ttf"


def ffmpeg(*args, cwd=None):
    subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", *args], check=True, cwd=cwd, timeout=120)


def make_clip(folder, name, audio_seconds=None):
    """1280x720, 10 s: red 0-3 s, green 3-6 s (frames dropped -> VFR gap), blue 6-10 s, burned-in clock."""
    clock = ",drawtext=fontfile=arial.ttf:text='%{pts\\:flt}':fontsize=96:fontcolor=white:x=(w-tw)/2:y=(h-th)/2"
    if not (folder / "arial.ttf").exists():
        clock = ""
    args = []
    for color, d in (("red", 3), ("green", 3), ("blue", 4)):
        args += ["-f", "lavfi", "-i", f"color=c={color}:s=1280x720:r=30:d={d}"]
    if audio_seconds:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={audio_seconds}"]
    args += ["-filter_complex", f"[0][1][2]concat=n=3:v=1:a=0{clock},select='not(between(t,3,6))'[v]",
             "-map", "[v]", "-fps_mode", "vfr", "-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if audio_seconds:
        args += ["-map", "3:a", "-c:a", "aac"]
    ffmpeg(*args, name, cwd=folder)
    return folder / name


def top_left_rgb(png):
    """Pixel (0,0) of an 8-bit RGB PNG; row 0's first pixel is stored raw under every PNG filter."""
    data = png.read_bytes()
    idat, pos = b"", 8
    while pos < len(data):
        length = int.from_bytes(data[pos:pos + 4], "big")
        if data[pos + 4:pos + 8] == b"IDAT":
            idat += data[pos + 8:pos + 8 + length]
        pos += 12 + length
    return tuple(zlib.decompress(idat)[1:4])


def run(*args, env=None):
    env = dict(env or os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True,
                          encoding="utf-8", errors="replace", env=env, timeout=600)


class ExtractFramesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.base = cls.tmp / "วิดีโอ ทดสอบ"
        cls.base.mkdir()
        if FONT.exists():
            shutil.copy(FONT, cls.base / "arial.ttf")
        cls.silent = make_clip(cls.base, "บันทึก หน้าจอ.mp4")
        cls.with_audio = make_clip(cls.base, "มีเสียง.mp4", audio_seconds=12)  # audio outlasts video
        ffmpeg("-f", "lavfi", "-i", "sine=duration=2", "-c:a", "aac", "เสียงอย่างเดียว.m4a", cwd=cls.base)
        cls.corrupt = cls.base / "เสีย.mp4"
        cls.corrupt.write_bytes(b"not a video " * 100)

    @classmethod
    def tearDownClass(cls):
        if not os.environ.get("KEEP_TEST_OUTPUT"):
            shutil.rmtree(cls.tmp, ignore_errors=True)
        else:
            print(f"\nkept test output: {cls.tmp}")

    def out(self, name):
        return self.base / "ผลลัพธ์ งาน" / name

    def assertNoTempLeft(self):
        self.assertEqual([p.name for p in self.out("x").parent.glob(".extract_frames-*")], [])

    def test_even_sampling_covers_whole_clip(self):
        before = hashlib.sha256(self.silent.read_bytes()).hexdigest()
        p = run("--input", str(self.silent), "--output-dir", str(self.out("even")))
        self.assertEqual(p.returncode, 0, p.stderr)
        m = json.loads((self.out("even") / "manifest.json").read_text(encoding="utf-8"))
        times = [f["timestamp_sec"] for f in m["frames"]]
        self.assertEqual(len(times), 10)  # 12 targets; 3 fall in the 3-6 s gap and share the frame at 2.967 s
        self.assertEqual(times[0], 0.0)
        self.assertEqual(times[-1], m["last_frame_sec"])
        self.assertGreater(times[-1], 9.9)
        self.assertEqual(times, sorted(times))
        self.assertFalse(m["has_audio"])
        self.assertEqual((m["width"], m["height"], m["frame_width"], m["frame_height"]), (1280, 720, 1280, 720))
        for f in m["frames"]:
            r, g, b = top_left_rgb(self.out("even") / f["file"])
            expected = r if f["timestamp_sec"] < 3 else b  # green 3-6 s was never on screen
            self.assertGreater(expected, 200, f)
            self.assertLess(g, 60, f)
        self.assertEqual(hashlib.sha256(self.silent.read_bytes()).hexdigest(), before)
        self.assertNoTempLeft()

    def test_timestamps_in_vfr_gap_and_tail_with_longer_audio(self):
        p = run("--input", str(self.with_audio), "--output-dir", str(self.out("detail")),
                "--timestamps", "1,4.5,9.99", "--max-width", "640")
        self.assertEqual(p.returncode, 0, p.stderr)
        m = json.loads((self.out("detail") / "manifest.json").read_text(encoding="utf-8"))
        self.assertTrue(m["has_audio"])
        self.assertEqual((m["frame_width"], m["frame_height"]), (640, 360))
        gap, tail = m["frames"][1], m["frames"][2]
        self.assertEqual(gap["requested_sec"], 4.5)
        self.assertAlmostEqual(gap["timestamp_sec"], 2.967, places=2)  # last frame shown before the gap
        self.assertGreater(top_left_rgb(self.out("detail") / gap["file"])[0], 200)  # red, not the next (blue) frame
        self.assertAlmostEqual(tail["timestamp_sec"], m["last_frame_sec"], places=3)
        self.assertGreater(top_left_rgb(self.out("detail") / tail["file"])[2], 200)

    def test_timestamps_out_of_range(self):
        p = run("--input", str(self.silent), "--output-dir", str(self.out("range")), "--timestamps", "5,99,-1")
        self.assertEqual(p.returncode, 2)
        self.assertIn("99", p.stderr)
        self.assertFalse(self.out("range").exists())
        p = run("--input", str(self.silent), "--output-dir", str(self.out("range")), "--timestamps", "5,abc")
        self.assertEqual(p.returncode, 2)
        self.assertIn("abc", p.stderr)

    def test_existing_output_is_not_overwritten(self):
        self.out("taken").mkdir(parents=True)
        (self.out("taken") / "keep.txt").write_text("mine", encoding="utf-8")
        p = run("--input", str(self.silent), "--output-dir", str(self.out("taken")))
        self.assertEqual(p.returncode, 2)
        self.assertIn("not an empty folder", p.stderr)
        self.assertEqual(os.listdir(self.out("taken")), ["keep.txt"])

    def test_corrupt_file(self):
        p = run("--input", str(self.corrupt), "--output-dir", str(self.out("corrupt")))
        self.assertEqual(p.returncode, 1)
        self.assertIn("corrupt or not a media file", p.stderr)
        self.assertFalse(self.out("corrupt").exists())

    def test_audio_only_file(self):
        p = run("--input", str(self.base / "เสียงอย่างเดียว.m4a"), "--output-dir", str(self.out("audio")))
        self.assertEqual(p.returncode, 1)
        self.assertIn("no video stream", p.stderr)

    def test_missing_input(self):
        p = run("--input", str(self.base / "ไม่มี ไฟล์.mp4"), "--output-dir", str(self.out("none")))
        self.assertEqual(p.returncode, 2)
        self.assertIn("input file not found", p.stderr)

    def test_ffmpeg_failure_leaves_no_partial_output(self):
        shim = self.tmp / "shim"
        shim.mkdir(exist_ok=True)
        if os.name == "nt":
            (shim / "ffmpeg.cmd").write_text("@echo simulated failure 1>&2\r\n@exit /b 1\r\n")
        else:
            (shim / "ffmpeg").write_text("#!/bin/sh\necho simulated failure >&2\nexit 1\n")
            (shim / "ffmpeg").chmod(0o755)
        env = dict(os.environ, PATH=f"{shim}{os.pathsep}{os.environ['PATH']}")
        p = run("--input", str(self.silent), "--output-dir", str(self.out("broken")), env=env)
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn("could not extract a frame", p.stderr)
        self.assertFalse(self.out("broken").exists())
        self.assertNoTempLeft()

    def test_missing_ffmpeg(self):
        env = dict(os.environ, PATH=str(Path(sys.executable).parent))
        p = run("--input", str(self.silent), "--output-dir", str(self.out("nodeps")), env=env)
        self.assertEqual(p.returncode, 2)
        self.assertIn("ffmpeg and ffprobe not found", p.stderr)
        self.assertIn("winget install", p.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
