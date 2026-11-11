"""Run the user's own logged-in agent CLI (Claude Code or Codex) headless. No API keys.

Neither CLI gets a tool that can read the disk: Claude receives the approved frames inline
(stdin stream-json, --tools ""), Codex via -i with its shell/file/image tools disabled.
Probed: both answered BLOCKED when asked to read a file next to the outbox.
npm .cmd shims are resolved to the real exe/js so arguments never pass through cmd.exe.
"""
import base64
import json
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from recorder import die_with_app

CREATE_NO_WINDOW = 0x08000000
PROVIDERS = {"claude": "Claude Code", "codex": "OpenAI Codex"}


class ProviderError(Exception):
    pass


def resolve(name):
    """Command prefix for an installed CLI, or None."""
    path = shutil.which(name)
    if not path:
        return None
    if path.lower().endswith((".cmd", ".bat")):
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        targets = re.findall(r'"%dp0%\\([^"]+\.(?:exe|js))"', text)
        if targets:
            target = Path(path).parent / targets[-1]
            if target.suffix.lower() == ".exe":
                return [str(target)]
            node = Path(path).parent / "node.exe"
            node = str(node) if node.exists() else shutil.which("node")
            return [node, str(target)] if node else None
    return [path]


def detect():
    """{key: {"name", "found", "version"}} for the provider picker."""
    out = {}
    for key, label in PROVIDERS.items():
        cmd = resolve(key)
        version = ""
        if cmd:
            try:
                p = subprocess.run(cmd + ["--version"], capture_output=True, encoding="utf-8", errors="replace",
                                   timeout=20, creationflags=CREATE_NO_WINDOW)
                version = (p.stdout or p.stderr).strip().splitlines()[0] if (p.stdout or p.stderr).strip() else ""
            except (OSError, subprocess.TimeoutExpired):
                cmd = None
        out[key] = {"name": label, "found": bool(cmd), "version": version}
    return out


def build_command(provider, schema, cwd, images):
    """(argv, output_file or None). `images` are bare file names inside cwd."""
    base = resolve(provider)
    if not base:
        raise ProviderError(f"ไม่พบ {PROVIDERS[provider]} ในเครื่อง ติดตั้งและ login ก่อน แล้วเปิดแอปใหม่")
    if provider == "claude":
        # Images go inside the stdin message (see claude_message) and every tool is off,
        # so Claude has no way to read files on disk (a Read tool could open files outside the outbox).
        argv = base + ["-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
                       "--json-schema", json.dumps(schema), "--safe-mode", "--strict-mcp-config",
                       "--no-session-persistence", "--tools", ""]
        return argv, None
    schema_file = Path(cwd) / "_schema.json"
    out_file = Path(cwd) / "_answer.json"
    schema_file.write_text(json.dumps(schema), encoding="utf-8")
    # Images are attached with -i, so Codex needs no tools: turn off everything that can read the disk.
    argv = base + ["exec", "--skip-git-repo-check", "--ephemeral", "--ignore-user-config", "-s", "read-only",
                   "-C", str(cwd), "--json", "--output-schema", schema_file.name, "-o", out_file.name]
    for feature in ("shell_tool", "unified_exec", "view_image", "browser_use", "apps"):
        argv += ["--disable", feature]
    if images:
        argv += ["--image=" + ",".join(images)]
    return argv + ["-"], out_file


def claude_message(prompt, cwd, images):
    """One stream-json user message: the prompt, then each image labelled with its file name."""
    content = [{"type": "text", "text": prompt}]
    for name in images:
        data = base64.b64encode((Path(cwd) / name).read_bytes()).decode()
        content += [{"type": "text", "text": f"Frame {name}:"},
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}}]
    return json.dumps({"type": "user", "message": {"role": "user", "content": content}}) + "\n"


def parse_claude(lines):
    for line in reversed(lines):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") == "result":
            if event.get("is_error"):
                raise ProviderError(f"Claude: {event.get('result') or event.get('subtype')}")
            data = event.get("structured_output")
            if data is None:
                data = _json_in(event.get("result", ""))
            return data
    raise ProviderError("Claude ไม่ส่งผลลัพธ์กลับมา: " + _tail(lines))


def _json_in(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise ProviderError("คำตอบไม่ใช่ JSON")
    return json.loads(m.group(0))


def _tail(lines, n=3):
    return " | ".join(l.strip()[:300] for l in lines[-n:] if l.strip()) or "ไม่มีข้อความ"


def run(provider, prompt, schema, cwd, images=(), timeout=900, on_progress=None, cancel=None):
    """Run one pass; returns the parsed JSON object. Raises ProviderError."""
    argv, out_file = build_command(provider, schema, cwd, list(images))
    if out_file and out_file.exists():
        out_file.unlink()
    proc = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            encoding="utf-8", errors="replace", creationflags=CREATE_NO_WINDOW)
    die_with_app(proc)
    lines, start = [], time.time()
    payload = claude_message(prompt, cwd, images) if provider == "claude" else prompt

    def feed():
        try:
            proc.stdin.write(payload)
            proc.stdin.close()
        except OSError:
            pass

    threading.Thread(target=feed, daemon=True).start()
    watchdog = threading.Thread(target=_watch, args=(proc, start, timeout, cancel), daemon=True)
    watchdog.start()
    for line in proc.stdout:
        lines.append(line)
        if on_progress:
            on_progress(len(lines), round(time.time() - start))
    proc.wait()
    if cancel is not None and cancel.is_set():
        raise ProviderError("ยกเลิกแล้ว")
    if time.time() - start >= timeout:
        raise ProviderError(f"เกินเวลา {timeout // 60} นาที")
    if provider == "claude":
        return parse_claude(lines)
    if proc.returncode != 0 or not out_file.exists():
        raise ProviderError(f"Codex ทำงานไม่สำเร็จ (exit {proc.returncode}): " + _tail(lines))
    return _json_in(out_file.read_text(encoding="utf-8", errors="replace"))


def _watch(proc, start, timeout, cancel):
    while proc.poll() is None:
        if (cancel is not None and cancel.is_set()) or time.time() - start >= timeout:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True,
                           creationflags=CREATE_NO_WINDOW)
            return
        time.sleep(0.5)
