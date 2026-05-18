"""
WebView2 고정 런타임 — 단일 exe 배포.

빌드 시 WebView2Runtime 이 exe 안에 포함되고,
첫 실행 때 %LOCALAPPDATA%\\3세대음방시스템\\WebView2Runtime 으로 풀립니다.
(배포는 exe 파일 하나만 하면 됨)
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from app_meta import EXE_NAME
from config_store import BUNDLE_DIR, INSTALL_DIR

_MARKER_EXE = "msedgewebview2.exe"
_MARKER_ALT = "msedge.exe"
_ENV_FOLDER = "WEBVIEW2_BROWSER_EXECUTABLE_FOLDER"
_RT_DIR_NAME = "WebView2Runtime"
_PERMISSION_MARKER = ".win10_acl_applied"
_CACHE_DIR = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / EXE_NAME / _RT_DIR_NAME


def _has_marker(folder: Path) -> bool:
    return (folder / _MARKER_EXE).is_file() or (folder / _MARKER_ALT).is_file()


def _folder_with_marker(root: Path) -> Path | None:
    if not root.is_dir():
        return None
    if _has_marker(root):
        return root.resolve()
    for child in sorted(root.iterdir(), reverse=True):
        if child.is_dir() and _has_marker(child):
            return child.resolve()
    for name in (_MARKER_EXE, _MARKER_ALT):
        for hit in root.rglob(name):
            return hit.parent.resolve()
    return None


def _bundled_source_folder() -> Path | None:
    """PyInstaller 번들(_MEIPASS) 또는 개발용 프로젝트 폴더."""
    for base in (BUNDLE_DIR, INSTALL_DIR, Path(__file__).resolve().parent):
        found = _folder_with_marker(base / _RT_DIR_NAME)
        if found:
            return found
    return None


def _copy_runtime_to(target: Path, source: Path) -> bool:
    try:
        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target)
        return _has_marker(target)
    except OSError:
        return False


def _prepare_cached_runtime(source: Path) -> Path | None:
    """단일 exe: 쓰기 가능한 로컬 캐시에 런타임 복사 (WebView2 동작 안정)."""
    cached = _folder_with_marker(_CACHE_DIR)
    if cached:
        return cached
    if _copy_runtime_to(_CACHE_DIR, source):
        return _CACHE_DIR.resolve()
    return None


def find_runtime_folder() -> Path | None:
    if sys.platform != "win32":
        return None

    # 예전 방식: exe 옆 WebView2Runtime 폴더(폴더 배포)
    beside_exe = _folder_with_marker(INSTALL_DIR / _RT_DIR_NAME)
    if beside_exe:
        return beside_exe

    source = _bundled_source_folder()
    if not source:
        return None

    if getattr(sys, "frozen", False):
        return _prepare_cached_runtime(source) or source

    return source


def bundled_runtime_available() -> bool:
    return find_runtime_folder() is not None


def find_bundled_browser_exe() -> str | None:
    folder = find_runtime_folder()
    if not folder:
        return None
    for name in (_MARKER_EXE, _MARKER_ALT):
        exe = folder / name
        if exe.is_file():
            return str(exe)
    return None


def _apply_win10_fixed_runtime_acl(runtime_dir: Path) -> None:
    if sys.platform != "win32":
        return
    marker = runtime_dir / _PERMISSION_MARKER
    if marker.exists():
        return
    path = str(runtime_dir)
    for grant in (
        "*S-1-15-2-2:(OI)(CI)(RX)",
        "*S-1-15-2-1:(OI)(CI)(RX)",
    ):
        try:
            subprocess.run(
                ["icacls", path, "/grant", grant],
                check=False,
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError:
            pass
    try:
        marker.write_text("1", encoding="utf-8")
    except OSError:
        pass


def _system_webview2_available() -> bool:
    """Check if system-installed WebView2 (Edge) runtime is present."""
    import winreg
    keys = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
        (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
    ]
    for hive, path in keys:
        try:
            with winreg.OpenKey(hive, path):
                return True
        except OSError:
            pass
    return False


def configure_bundled_webview2() -> bool:
    folder = find_runtime_folder()
    if folder:
        _apply_win10_fixed_runtime_acl(folder)
        os.environ[_ENV_FOLDER] = str(folder)
        return True
    # In dev mode (not frozen), allow the system WebView2 runtime (Edge) to be used.
    if not getattr(sys, "frozen", False):
        if sys.platform == "win32" and _system_webview2_available():
            return True
        # Even if registry key isn't found, let it try — WebView2 may still work
        # (e.g. if Edge is installed but detection fails).
        return True
    return False


def runtime_status_message() -> str:
    if find_runtime_folder():
        return "WebView2 런타임 준비됨"
    return (
        "exe 안에 WebView2 런타임이 없습니다.\n"
        "빌드 PC에서 prepare_webview2_runtime.py 실행 후\n"
        "pyinstaller 로 다시 빌드하세요."
    )
