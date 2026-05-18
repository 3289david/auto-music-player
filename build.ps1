# 3세대 음방시스템 — exe 빌드
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "=== 3세대 음방시스템 빌드 ===" -ForegroundColor Cyan

if (-not (Test-Path "14720088.png")) {
    Write-Host "아이콘 없음: 14720088.png" -ForegroundColor Red
    exit 1
}

python -m pip install -q -r requirements.txt pyinstaller pillow

python -c @"
from pathlib import Path
from PIL import Image
img = Image.open('14720088.png').convert('RGBA')
img.save('app_icon.ico', format='ICO', sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)])
print('app_icon.ico OK')
"@

pyinstaller --noconfirm --clean --icon=app_icon.ico --name=3세대음방시스템 `
    --add-data "panel;panel" --add-data "broadcast;broadcast" `
    --hidden-import=engineio.async_drivers.eventlet `
    --hidden-import=eventlet.hubs.selects `
    --hidden-import=flask_socketio --hidden-import=flask_login --hidden-import=flask_wtf `
    --hidden-import=yt_dlp --hidden-import=bcrypt --hidden-import=screeninfo `
    --collect-submodules=yt_dlp `
    main.py

if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "완료: dist\3세대음방시스템.exe" -ForegroundColor Green
Write-Host "exe 옆에 config.json, uploads 가 생성됩니다."
