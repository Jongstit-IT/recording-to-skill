"""Render a session's analysis and skill draft to analysis.md and SKILL.md."""
import json
import re
from pathlib import Path

LABELS = {
    "th": {"goal": "เป้าหมาย", "summary": "สรุป", "steps": "ขั้นตอน", "evidence": "หลักฐาน", "basis": "ที่มา",
           "uncertain": "สิ่งที่ยังไม่แน่ใจ", "inputs": "Input", "how": "วิธีได้ค่า", "pre": "สิ่งที่ต้องมีก่อนเริ่ม",
           "output": "ผลลัพธ์", "errors": "กรณีผิดพลาด", "assume": "สมมติฐานที่ต้องยืนยัน", "none": "(ไม่มี)",
           "observed": "เห็นในภาพ", "inferred": "อนุมาน", "source": "ที่มา", "sent": "ภาพที่ส่งให้ AI"},
    "en": {"goal": "Goal", "summary": "Summary", "steps": "Steps", "evidence": "Evidence", "basis": "Basis",
           "uncertain": "Uncertainties to check", "inputs": "Inputs", "how": "How to get", "pre": "Prerequisites",
           "output": "Output", "errors": "Errors and edge cases", "assume": "Assumptions to confirm", "none": "(none)",
           "observed": "observed", "inferred": "inferred", "source": "Source", "sent": "Frames sent to AI"},
}


def skill_name(name):
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:64].strip("-")
    return "recorded-task" if s in ("", "recording-to-skill") else s


def yaml_scalar(text):
    """One-line YAML value; JSON-quoted (valid YAML) when it holds YAML-special characters."""
    one = " ".join(str(text).split()).replace("<", "(").replace(">", ")")
    if not one or re.search(r"[:#'\"{}\[\],&*!|%@`]", one) or one[0] in "-?":
        return json.dumps(one, ensure_ascii=False)
    return one


def _bullets(items, none):
    items = [i for i in items if str(i).strip()]
    return "\n".join(f"- {i}" for i in items) if items else none


def _cell(text):
    return " ".join(str(text).split()).replace("|", "\\|")


def skill_md(skill, lang):
    L = LABELS[lang]
    inputs = "\n".join(f"- **{i['name']}**: {i['description']} — {L['how']}: {i['how_to_get']}"
                       for i in skill["inputs"]) or L["none"]
    steps = "\n".join(f"{n}. **{s['title']}**" + (f" `{s['tool']}`" if s.get("tool") else "") + f"\n   {s['detail']}"
                      for n, s in enumerate(skill["steps"], 1))
    return f"""---
name: {skill_name(skill['name'])}
description: {yaml_scalar(skill['description'])}
---

# {skill_name(skill['name'])}

## {L['inputs']}
{inputs}

## {L['pre']}
{_bullets(skill['prerequisites'], L['none'])}

## {L['steps']}
{steps}

## {L['output']}
{skill['output'] or L['none']}

## {L['errors']}
{_bullets(skill['errors'], L['none'])}

## {L['assume']}
{_bullets(skill['assumptions'], L['none'])}
"""


def analysis_md(data, lang):
    L, a = LABELS[lang], data["analysis"]
    sent = [f for f in data["frames"] if not f["excluded"]]
    rows = "\n".join(f"| {n} | **{_cell(s['title'])}** {_cell(s['detail'])} | {_cell(', '.join(s['frames']))} | "
                     f"{L.get(s['basis'], s['basis'])} |" for n, s in enumerate(a["steps"], 1))
    duration = sum(s["duration"] for s in data.get("timing", []))
    return f"""# {a['task_title']}

{L['source']}: session {data['id']} · {duration:.0f} s · AI: {data['provider']} · {L['sent']}: {len(sent)}/{len(data['frames'])}

## {L['goal']}
{data.get('goal') or L['none']}

## {L['summary']}
{a['summary']}

## {L['steps']}
| # | {L['steps']} | {L['evidence']} | {L['basis']} |
| --- | --- | --- | --- |
{rows}

## {L['uncertain']}
{_bullets(a['uncertainties'], L['none'])}
"""


def export(data, folder):
    """Write <folder>/<name>/SKILL.md + analysis.md; refuses to overwrite. Returns the skill folder."""
    target = Path(folder) / skill_name(data["skill"]["name"])
    if target.exists():
        raise FileExistsError(f"มีโฟลเดอร์นี้อยู่แล้ว: {target}")
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text(skill_md(data["skill"], data["lang"]), encoding="utf-8")
    (target / "analysis.md").write_text(analysis_md(data, data["lang"]), encoding="utf-8")
    return target
