@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo === 3세대 음방시스템 빌드 (단일 exe) ===

if not exist "14720088.png" (
    echo [오류] 14720088.png 가 이 폴더에 없습니다.
    pause
    exit /b 1
)

python -m pip install -q -r requirements.txt pyinstaller
if errorlevel 1 (
    echo [오류] pip 설치 실패
    pause
    exit /b 1
)

python -c "from PIL import Image; Image.open('14720088.png').convert('RGBA').save('app_icon.ico', format='ICO', sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)]); print('app_icon.ico OK')"
if errorlevel 1 (
    echo [오류] 아이콘 변환 실패
    pause
    exit /b 1
)

echo.
echo [1/2] WebView2 런타임 다운로드 ^(약 250MB, exe에 포함됨^)…
python prepare_webview2_runtime.py
if errorlevel 1 (
    echo [오류] WebView2Runtime 준비 실패
    pause
    exit /b 1
)

if not exist "WebView2Runtime\msedgewebview2.exe" (
    if not exist "WebView2Runtime\msedge.exe" (
        echo [오류] WebView2Runtime 에 브라우저 exe 없음
        pause
        exit /b 1
    )
)

echo.
echo [2/2] 단일 exe 빌드 ^(수 분 소요, 용량 약 400~600MB^)…
pyinstaller --noconfirm --clean build.spec
if errorlevel 1 (
    echo [오류] 빌드 실패
    pause
    exit /b 1
)

echo.
echo ========================================
echo  완료: dist\3세대음방시스템.exe
echo.
echo  다른 PC에는 이 exe 파일만 복사하면 됩니다.
echo  첫 실행 시 WebView2가 자동으로 풀립니다
echo  ^(%LOCALAPPDATA%\3세대음방시스템\WebView2Runtime^).
echo.
echo  설정·플레이리스트는 exe 옆에 저장됩니다.
echo ========================================
pause
