**มีอะไรใหม่ใน v0.1.2**
- มีกรอบแดงรอบจอที่กำลังอัด (สีเหลือง = พัก) และกะพริบเมื่อเลือกจอ กรอบนี้ไม่ติดไปในวิดีโอ
- ไม่มีหน้าต่าง terminal เด้งขึ้นตอนตัดภาพแล้ว แอปแสดงหน้าจอ "กำลังตัดภาพ x/y" แทน
- ตัดภาพเร็วขึ้น: ตัด 4 ภาพพร้อมกันและอัดวิดีโอให้ seek เร็วขึ้น (คลิป 42 วินาที 33 ภาพ: จาก 18 วินาที เหลือประมาณ 3 วินาที)
- AI เร็วขึ้น (ทดสอบ 24 ภาพ ครั้งเดียว, วิเคราะห์ + สร้าง skill):
  - Codex: 95 → 63 วินาที เฉพาะเครื่องที่ตั้ง `service_tier = "fast"` ไว้ใน `~/.codex/config.toml` (แอปใช้ค่านี้ตามที่ตั้งไว้)
  - Claude: 5 นาที → 1 นาที 20 วินาที (ใช้ effort ระดับ medium)

**ดาวน์โหลด `RecordingToSkill.exe` แล้วดับเบิลคลิกได้เลย ไม่ต้องติดตั้ง** (Windows 10/11 x64)

ก่อนใช้ต้องมี [Claude Code](https://code.claude.com) หรือ [OpenAI Codex CLI](https://github.com/openai/codex) ติดตั้งและ login ไว้ในเครื่อง แอปใช้ AI ผ่าน login เดิมของคุณ ไม่ต้องใส่ API key

ไฟล์นี้ยังไม่ได้ sign: ถ้าขึ้นหน้าต่าง **"Windows protected your PC"** ให้กด **More info → Run anyway**

แพ็กเกจรวม FFmpeg 9.0.2 (GPLv3) ไว้ด้วย รายละเอียดอยู่ที่ [licenses/ffmpeg.txt](https://github.com/Jongstit-IT/recording-to-skill/blob/main/licenses/ffmpeg.txt)

---

**Download `RecordingToSkill.exe` and double-click it. No install needed.** Requires Claude Code or Codex CLI installed and signed in. Unsigned build: on the SmartScreen prompt choose **More info → Run anyway**. Bundles FFmpeg 9.0.2 (GPLv3).
