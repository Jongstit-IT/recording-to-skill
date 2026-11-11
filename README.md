# Recording to Skill

อัดหน้าจอการทำงานครั้งเดียว แล้วให้ AI เปลี่ยนเป็น `SKILL.md` ที่ Claude Code หรือ Codex ใช้ทำงานนั้นซ้ำได้

[English below](#english)

## ดาวน์โหลด

1. ไปที่ [Releases](https://github.com/Jongstit-IT/recording-to-skill/releases/latest) แล้วโหลด `RecordingToSkill.exe` (Windows x64 ไม่ต้องติดตั้ง ทดสอบบน Windows 11 ส่วน Windows 10 ยังไม่ได้ทดสอบ)
2. ดับเบิลคลิก ถ้าขึ้น **"Windows protected your PC"** ให้กด **More info → Run anyway** (ไฟล์ยังไม่ได้ sign) ระหว่างโปรแกรมเปิดจะมีหน้าจอ "กำลังเปิดโปรแกรม" ขึ้น ครั้งแรกหลังดาวน์โหลดอาจรอ 10–30 วินาทีเพราะ antivirus สแกนไฟล์ ถ้ากดเปิดซ้ำ จะเรียกหน้าต่างเดิมขึ้นมาแทนการเปิดใหม่
3. ต้องมี AI อย่างน้อย 1 ตัวที่ติดตั้งและ login ไว้แล้ว แอปจะใช้ login เดิม **ไม่ต้องใส่ API key**
   - [Claude Code](https://code.claude.com): `npm install -g @anthropic-ai/claude-code` แล้วรัน `claude` หนึ่งครั้งเพื่อ login
   - [OpenAI Codex CLI](https://github.com/openai/codex): `npm install -g @openai/codex` แล้วรัน `codex` หนึ่งครั้งเพื่อ login

## วิธีใช้

1. **อัด:** เลือกจอ (จอที่เลือกจะกะพริบกรอบแดง) และ AI แล้วกดปุ่มแดง (หรือ `Ctrl+Alt+R`) ทำงานตามปกติจนเสร็จ แล้วกดหยุด ระหว่างอัดกด `Ctrl+Alt+P` เพื่อพักได้
   - ระหว่างอัดมีกรอบแดงรอบจอที่กำลังอัด (สีเหลือง = พักอยู่) กรอบนี้ไม่ติดไปในวิดีโอ
2. **ตรวจภาพ:** แอปตัดภาพก่อนคลิกแต่ละครั้ง (มีกรอบแดงตรงจุดที่คลิก) ตอนสลับหน้าต่าง และช่วงที่ว่างนาน ติ๊กภาพที่มีข้อมูลลับออก แล้วพิมพ์เป้าหมายของงาน
3. **วิเคราะห์:** AI ดูภาพแล้วสรุปเป็น step แก้ เรียงลำดับใหม่ เพิ่ม หรือลบได้ และบันทึกอัตโนมัติ
4. **สร้าง skill:** AI เขียน skill ที่ใช้ซ้ำได้ (input, ขั้นตอน, เครื่องมือ, กรณีผิดพลาด) แก้ในการ์ดได้ทุกช่อง
5. **Export:** เลือกโฟลเดอร์ แอปจะสร้าง `<ชื่อ-skill>/SKILL.md` + `analysis.md` จากนั้นคัดลอกทั้งโฟลเดอร์ไปที่ `.claude/skills/` (Claude Code) หรือ `.agents/skills/` (Codex)

ระหว่างรอ AI กดยกเลิกได้ จากการทดสอบ 24 ภาพ (ทดสอบครั้งเดียว เวลาจริงขึ้นกับงานและเครือข่าย):
- วิเคราะห์: Claude ประมาณ 30 วินาที, Codex ประมาณ 30–40 วินาที
- สร้าง skill: อีกประมาณ 30–60 วินาที
- Claude ใช้ effort ระดับ medium เสมอ ส่วน Codex ใช้ `service_tier` ตามที่ตั้งไว้ใน `~/.codex/config.toml` (ถ้าตั้ง `service_tier = "fast"` ไว้ จะเร็วขึ้นประมาณ 1 ใน 3)

## ความเป็นส่วนตัว

- อัดภาพจอ เวลา/ตำแหน่งที่คลิก และชื่อหน้าต่าง **ไม่บันทึกสิ่งที่พิมพ์**
- ทุกอย่างเก็บอยู่ในเครื่องที่ `%LOCALAPPDATA%\RecordingToSkill\sessions\` จนกว่าคุณจะกด "วิเคราะห์"
- ตอนวิเคราะห์ AI ได้รับเฉพาะภาพที่ติ๊กไว้และ timeline ช่วงนั้น โดยส่งแนบไปกับข้อความ และแอปปิดเครื่องมืออ่านไฟล์หรือรันคำสั่งของ AI ทั้งหมด
  - ทดสอบแล้ว: Claude Code และ Codex เปิดไฟล์อื่นในเครื่องไม่ได้
  - ภาพจะถูกส่งให้ Anthropic หรือ OpenAI ตาม AI ที่เลือก
- กด × ที่ session เพื่อลบวิดีโอ ภาพ และผลวิเคราะห์ทั้งหมด

## ข้อจำกัด

- Windows เท่านั้น อัดได้ครั้งละ 1 จอ สูงสุด 15 นาที และยังไม่มีการอัดเสียง
- skill ที่ได้เป็นร่าง ต้องให้คนตรวจหัวข้อ "สมมติฐานที่ต้องยืนยัน" ก่อนใช้จริง
- AI เห็นเฉพาะสิ่งที่อยู่บนจอ คีย์ลัด, clipboard และสิ่งที่พิมพ์แต่อ่านไม่ออกจะถูกระบุว่าไม่ทราบ
- Gemini: Gemini CLI ปิดสำหรับผู้ใช้ทั่วไปแล้ว ตัวแทนคือ Antigravity CLI ซึ่งจะเพิ่มเมื่อทดสอบได้ว่าอ่านภาพแบบ headless ได้

## Skill แบบไม่ใช้แอป

ถ้าอัดด้วย Snipping Tool เอง ใช้ skill [`recording-to-skill/`](recording-to-skill/README.md) ใน Claude Code หรือ Codex ได้โดยตรง

## สำหรับนักพัฒนา

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install pywebview==6.2.1 pyinstaller==6.22.3
python app\main.py                # รันจากซอร์ส (ต้องมี ffmpeg ใน PATH)
python tests\test_app.py          # unit test ของแอป
python tests\test_extract_frames.py
.\build.ps1                       # สร้าง dist\RecordingToSkill.exe (ดาวน์โหลด FFmpeg ที่ตรวจ SHA-256 แล้ว)
```

Push tag `v*` แล้ว GitHub Actions จะ build, test และแนบ .exe ไว้ที่ Releases

## ใบอนุญาตและที่มา

- โค้ดใช้ MIT License ([LICENSE](LICENSE))
- `.exe` รวม FFmpeg 9.0.2 (GPLv3) ไว้ด้วย ดูรายละเอียดที่ [licenses/ffmpeg.txt](licenses/ffmpeg.txt)
- แนวคิด (อัด → สรุป step → แก้ → สร้าง skill) ได้แรงบันดาลใจจาก [microsoft/skill-recorder](https://github.com/microsoft/skill-recorder) (MIT) โดยไม่ได้คัดลอกโค้ดหรือ prompt มา และโปรเจกต์นี้ไม่เกี่ยวข้องกับ Microsoft

---

## English

Record yourself doing a task once; an AI turns it into a `SKILL.md` that Claude Code or Codex can repeat.

- **Download** `RecordingToSkill.exe` from [Releases](https://github.com/Jongstit-IT/recording-to-skill/releases/latest) (Windows x64, portable; tested on Windows 11 only). It is unsigned: on SmartScreen choose *More info → Run anyway*.
- **Requires** Claude Code or OpenAI Codex CLI, installed and signed in. The app runs them headless with your existing login; no API keys.
- **Flow:**
  1. Record (`Ctrl+Alt+R`, pause with `Ctrl+Alt+P`). A red frame marks the monitor being recorded (amber while paused); it is not captured in the video.
  2. Review the extracted frames and untick anything sensitive.
  3. Analyze, then edit, reorder, add or delete steps.
  4. Create the skill and edit its cards.
  5. Export `<name>/SKILL.md` + `analysis.md`.
- **Privacy:**
  - Captures the screen, click times and positions, and window titles. Keystrokes are never recorded.
  - Data stays in `%LOCALAPPDATA%\RecordingToSkill` until you press Analyze.
  - Only the approved frames and their timeline are sent to the AI, attached to the prompt. The app runs the CLI with every file-reading and shell tool turned off; a probe confirmed neither Claude Code nor Codex could open other files.
- **License:** MIT. The exe bundles FFmpeg 9.0.2 (GPLv3, see `licenses/ffmpeg.txt`). Inspired by microsoft/skill-recorder (MIT); this project is not affiliated with Microsoft.
