# recording-to-skill

Skill สำหรับ Claude Code, Codex และ Gemini CLI: รับวิดีโอ MP4 ที่อัดด้วย Snipping Tool พร้อมเป้าหมายงาน แล้วแยกภาพจากวิดีโอในเครื่อง agent ใน session ปัจจุบันจะดูภาพ เขียน `analysis.md` และสร้าง `generated/<task-name>/SKILL.md` สำหรับทำงานนั้นซ้ำ

ไม่มีการเรียก Copilot, LLM อื่น หรือ API key การวิเคราะห์ทั้งหมดใช้ session Claude Code/Codex/Gemini CLI ที่เปิดอยู่

## ไฟล์

| ไฟล์ | หน้าที่ |
| --- | --- |
| `SKILL.md` | ขั้นตอนที่ agent ทำตาม |
| `scripts/extract_frames.py` | ตรวจวิดีโอด้วย ffprobe แยกภาพ PNG และเขียน `manifest.json` (ใช้ Python standard library) |

## 1. ติดตั้ง dependency

ต้องมี Python 3.8 ขึ้นไป และ FFmpeg (มี `ffprobe` มาด้วย) ใน PATH

```powershell
winget install --id Gyan.FFmpeg -e   # Windows แล้วเปิด terminal ใหม่
ffmpeg -version; ffprobe -version; python --version
```

macOS: `brew install ffmpeg` · Debian/Ubuntu/WSL: `sudo apt install ffmpeg`

## 2. ติดตั้ง skill

คัดลอกทั้งโฟลเดอร์ รวม `scripts/` ไปยังตำแหน่งใดตำแหน่งหนึ่ง

| โปรแกรม | เฉพาะโปรเจกต์ | ส่วนตัว (ทุกโปรเจกต์) |
| --- | --- | --- |
| Claude Code | `.claude\skills\recording-to-skill\` | `~\.claude\skills\recording-to-skill\` |
| Codex | `.agents\skills\recording-to-skill\` | `~\.agents\skills\recording-to-skill\` |
| Gemini CLI | `.agents\skills\recording-to-skill\` (หรือ `.gemini\skills\`) | `~\.agents\skills\recording-to-skill\` (หรือ `~\.gemini\skills\`) |

Codex และ Gemini CLI อ่าน `.agents\skills` เหมือนกัน ติดตั้งครั้งเดียวใช้ได้ทั้งสองโปรแกรม

PowerShell: แก้ `$src` ให้เป็นพาธของโฟลเดอร์นี้ และเลือก `$dest` หนึ่งบรรทัด สำหรับแบบเฉพาะโปรเจกต์ให้รันในโฟลเดอร์ของโปรเจกต์นั้น คำสั่งนี้จะไม่ทับของเดิม ถ้ามีโฟลเดอร์อยู่แล้วจะหยุดและแจ้ง

```powershell
$src  = "C:\path\to\recording-to-skill"                 # โฟลเดอร์นี้ใน repo ที่ clone หรือแตก zip มา
$dest = ".claude\skills\recording-to-skill"             # Claude Code เฉพาะโปรเจกต์
# $dest = "$HOME\.claude\skills\recording-to-skill"     # Claude Code ส่วนตัว
# $dest = ".agents\skills\recording-to-skill"           # Codex / Gemini CLI เฉพาะโปรเจกต์
# $dest = "$HOME\.agents\skills\recording-to-skill"     # Codex / Gemini CLI ส่วนตัว
if (Test-Path $dest) { "มีอยู่แล้ว: $dest (ลบหรือย้ายเองก่อนติดตั้งใหม่)" } else { New-Item -ItemType Directory -Force (Split-Path $dest) | Out-Null; Copy-Item -Recurse $src $dest; "ติดตั้งแล้ว: $dest" }
```

bash / WSL:

```bash
src=/path/to/recording-to-skill
dest=~/.claude/skills/recording-to-skill   # หรือ ~/.agents/skills/recording-to-skill (Codex / Gemini CLI)
if [ -e "$dest" ]; then echo "exists: $dest"; else mkdir -p "$(dirname "$dest")" && cp -r "$src" "$dest" && echo "installed: $dest"; fi
```

หลังติดตั้ง:

- Claude Code: ถ้าไม่เห็น `/recording-to-skill` ในเมนู `/` ให้เริ่ม session ใหม่ (กรณีเพิ่งสร้างโฟลเดอร์ skills ครั้งแรก)
- Codex: ตรวจพบ skill ใหม่อัตโนมัติ ถ้าไม่ขึ้นใน `/skills` ให้รีสตาร์ต Codex
- Gemini CLI: รัน `/skills reload` แล้วตรวจด้วย `/skills list`

## 3. ใช้งาน

1. กด Win + Shift + R เลือกพื้นที่ กดเริ่มอัด ทำงานให้จบ กด Stop แล้วบันทึกเป็น MP4
2. เรียก skill ในโฟลเดอร์ที่ต้องการเก็บผลลัพธ์

Claude Code:

```text
/recording-to-skill วิเคราะห์ไฟล์ C:\Recordings\demo.mp4 เป้าหมายคือรวบรวม GitHub issues ตามเงื่อนไขแล้วทำรายงาน สร้าง analysis.md และ skill สำหรับทำงานนี้ซ้ำ ระบุส่วนที่ดูจากวิดีโอไม่ได้ให้ชัดเจน
```

Codex: ใช้ `$recording-to-skill` แทน `/recording-to-skill` หรือเลือกจาก `/skills`

Gemini CLI: ไม่มีคำสั่งเรียก skill ตรง ๆ ให้พิมพ์ว่า "ใช้ recording-to-skill วิเคราะห์ไฟล์ ..." แล้วกดอนุญาตเมื่อ Gemini ขอเปิดใช้ skill

ทุกโปรแกรมเรียก skill เองได้เมื่อคำสั่งตรงกับ description เช่น "ใช้ recording-to-skill วิเคราะห์ไฟล์ ..."

ผลลัพธ์จะอยู่ในโฟลเดอร์ที่ทำงานอยู่:

```text
work/<task-name>/frames/            ภาพภาพรวม + manifest.json
work/<task-name>/frames-detail-1/   ภาพที่ agent ขอเพิ่มในช่วงกำกวม
work/<task-name>/analysis.md        ขั้นตอน หลักฐาน และสิ่งที่ยังไม่แน่ใจ
generated/<task-name>/SKILL.md      skill ของงานที่สาธิต (ร่างให้ตรวจ)
```

ตรวจ `analysis.md` หัวข้อ "Uncertainties to check" ก่อน แล้วค่อยคัดลอก `generated/<task-name>/` ไปติดตั้งด้วยวิธีเดียวกับข้อ 2

## ใช้สคริปต์โดยตรง

```powershell
python recording-to-skill/scripts/extract_frames.py --input "C:\Recordings\demo.mp4" --output-dir "work/demo" --max-frames 12
python recording-to-skill/scripts/extract_frames.py --input "C:\Recordings\demo.mp4" --output-dir "work/demo-detail" --timestamps "5,12.5,40"
```

| ตัวเลือก | ความหมาย |
| --- | --- |
| `--input` | ไฟล์วิดีโอ สคริปต์จะไม่แก้ไขไฟล์นี้ |
| `--output-dir` | โฟลเดอร์ใหม่หรือโฟลเดอร์ว่าง ถ้ามีไฟล์อยู่แล้วจะหยุด ไม่เขียนทับ |
| `--max-frames` | จำนวนภาพที่กระจายทั้งคลิป ตั้งแต่ภาพแรกถึงภาพสุดท้าย (ค่าเริ่มต้น 12) |
| `--timestamps` | วินาทีที่ต้องการคั่นด้วย comma ต้องอยู่ในช่วงความยาววิดีโอ ใช้แทน `--max-frames` |
| `--max-width` | ย่อภาพที่กว้างกว่านี้โดยรักษาอัตราส่วน ไม่ขยายภาพ (ค่าเริ่มต้น 1920) |

ภาพแต่ละภาพคือสิ่งที่อยู่บนจอ ณ `timestamp_sec` ใน manifest โดยเลือกเฟรมจริงล่าสุดที่ไม่เกินเวลาที่ขอ ส่วนเวลาที่ขอจะเก็บใน `requested_sec` วิธีนี้ใช้ได้กับวิดีโอ frame rate ไม่คงที่ของ Snipping Tool ถ้าหลายเวลาตกที่เฟรมเดียวกันจะเก็บภาพเดียว

Exit code: `0` สำเร็จ · `1` วิดีโอเสีย ไม่มี video stream หรือ FFmpeg ผิดพลาด · `2` ใช้ตัวเลือกผิด โฟลเดอร์ผลลัพธ์มีอยู่แล้ว หรือไม่พบ ffmpeg/ffprobe

## ข้อจำกัด

- ไม่ถอดเสียง ถ้าวิดีโอมีเสียง ให้ส่งข้อความบรรยายหรือ transcript มาเอง
- เลือกภาพแบบกระจายตามเวลา ไม่ตรวจการเปลี่ยนฉากอัตโนมัติ การกระทำสั้น ๆ ระหว่างภาพอาจหลุด agent ต้องขอภาพเพิ่มด้วย `--timestamps`
- ไม่เห็นสิ่งที่ไม่ปรากฏบนจอ เช่น clipboard คีย์ลัด หรือคำสั่งที่ซ่อนอยู่ ผลจะระบุเป็น unknown
- ความแม่นยำขึ้นกับความสามารถอ่านภาพของ host ถ้า Codex เปิดภาพในเครื่องเองไม่ได้ ให้แนบภาพด้วย `codex -i`
- skill ที่สร้างออกมาเป็นร่าง ต้องให้คนตรวจก่อนใช้จริง
- ยังไม่ได้ทดสอบกับ Gemini CLI จริง ข้อมูลมาจากเอกสาร geminicli.com (อัปเดต เม.ย. 2026) ซึ่งแจ้งว่า Gemini CLI ถูกแทนที่ด้วย Antigravity CLI ตั้งแต่ 18 มิ.ย. 2026

## ที่มา

แนวคิดการวิเคราะห์ (แยกเป้าหมายจากหลักฐาน ตัดขั้นตอนนอกเรื่อง ทำค่าตัวอย่างให้เป็น input และเลือก CLI ก่อน UI) ปรับจาก [microsoft/skill-recorder](https://github.com/microsoft/skill-recorder) commit `505c97ae47be5642c0e1b44ebb8d1c1530c298fa` (MIT License, Copyright (c) Microsoft Corporation) ไม่ได้คัดลอก prompt หรือโค้ดมา
