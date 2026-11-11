# Build dist\RecordingToSkill.exe (one file, FFmpeg bundled).
# Needs: Python 3.12+ with `pip install pywebview==6.2.1 pyinstaller==6.22.3`
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$ff = Join-Path $root "build\ffmpeg"

if (-not (Test-Path "$ff\ffmpeg.exe")) {
    # FFmpeg 9.0.2 essentials (GPLv3) by Gyan Doshi, pinned by SHA-256
    $url = "https://github.com/GyanD/codexffmpeg/releases/download/9.0.2/ffmpeg-9.0.2-essentials_build.zip"
    $sha = "60F467265B1E312373DBCD92200C2618A74850F98D3D078E94296BB3FA2047BA"
    $zip = Join-Path $root "build\ffmpeg.zip"
    New-Item -ItemType Directory -Force (Split-Path $zip) | Out-Null
    Invoke-WebRequest $url -OutFile $zip
    if ((Get-FileHash $zip -Algorithm SHA256).Hash -ne $sha) { throw "ffmpeg.zip checksum mismatch" }
    Expand-Archive $zip (Join-Path $root "build\ffzip") -Force
    New-Item -ItemType Directory -Force $ff | Out-Null
    $bin = (Get-ChildItem (Join-Path $root "build\ffzip") -Recurse -Filter ffmpeg.exe | Select-Object -First 1).DirectoryName
    Copy-Item "$bin\ffmpeg.exe", "$bin\ffprobe.exe" $ff
    Copy-Item (Get-ChildItem (Join-Path $root "build\ffzip") -Recurse -Filter LICENSE | Select-Object -First 1).FullName "$ff\LICENSE.txt"
}

$ErrorActionPreference = "Continue"  # PyInstaller logs to stderr; Windows PowerShell 5.1 would treat that as fatal
pyinstaller --noconfirm --onefile --noconsole --name RecordingToSkill `
    --distpath "$root\dist" --workpath "$root\build\pyi" --specpath "$root\build" `
    --paths "$root\app" --paths "$root\recording-to-skill\scripts" `
    --add-data "$root\app\ui;ui" `
    --splash "$root\app\splash.png" `
    --add-binary "$ff\ffmpeg.exe;ffmpeg" --add-binary "$ff\ffprobe.exe;ffmpeg" --add-data "$ff\LICENSE.txt;ffmpeg" `
    "$root\app\main.py"
if ($LASTEXITCODE) { throw "pyinstaller failed" }
