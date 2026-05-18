# -*- mode: python ; coding: utf-8 -*-
# PyInstaller — 단일 exe (WebView2Runtime 포함, 배포는 exe 하나)
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

block_cipher = None
root = Path(SPECPATH)
binaries = []

datas = [
    (str(root / "panel"), "panel"),
    (str(root / "broadcast"), "broadcast"),
    (str(root / "14720088.png"), "."),
]
_ico = root / "app_icon.ico"
if _ico.is_file():
    datas.append((str(_ico), "."))

_wv2 = root / "WebView2Runtime"
if _wv2.is_dir():
    datas.append((str(_wv2), "WebView2Runtime"))
else:
    print(
        "WARNING: WebView2Runtime 폴더 없음 — "
        "빌드 전에 python prepare_webview2_runtime.py 를 실행하세요."
    )

for pkg in ("flask", "flask_login", "werkzeug", "jinja2", "yt_dlp"):
    try:
        datas += collect_data_files(pkg, include_py_files=True)
    except Exception:
        pass

hiddenimports = [
    "engineio.async_drivers.threading",
    "simple_websocket",
    "dns",
    "dns.resolver",
    "bcrypt",
    "screeninfo",
    "pystray",
    "pystray._base",
    "pystray._win32",
    "PIL",
    "PIL.Image",
    "PIL.ImageDraw",
    "PIL._imaging",
    "webview2",
    "win32api",
    "win32con",
    "win32gui",
    "pythoncom",
    "pywintypes",
    "six",
]

_collect_packages = (
    "engineio",
    "socketio",
    "flask_socketio",
    "flask",
    "flask_login",
    "flask_wtf",
    "werkzeug",
    "jinja2",
    "itsdangerous",
    "click",
    "markupsafe",
    "wtforms",
    "yt_dlp",
    "cryptography",
    "certifi",
    "urllib3",
    "requests",
    "pystray",
    "PIL",
)

for pkg in ("pystray", "PIL", "webview2", "pywin32"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

for pkg in _collect_packages:
    try:
        hiddenimports += collect_submodules(pkg)
    except Exception:
        pass

hiddenimports = sorted(set(hiddenimports))

a = Analysis(
    ["main.py"],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "eventlet",
        "gevent",
        "matplotlib",
        "numpy",
        "pandas",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

_icon = root / "app_icon.ico"
if not _icon.is_file():
    _icon = root / "14720088.png"

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="3세대음방시스템",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(_icon) if _icon.is_file() else None,
)
