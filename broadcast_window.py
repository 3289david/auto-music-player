"""
방송 화면 창 열기/닫기 (Edge / Chrome 키오스크 전체화면).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from app_meta import APP_NAME
from config_store import load_config
from panel_log import get_logger

_browser_proc: subprocess.Popen | None = None
_external_yt_proc: subprocess.Popen | None = None

_CHROMIUM_AUTOPLAY_FLAGS = [
    "--autoplay-policy=no-user-gesture-required",
    "--disable-features=PreloadMediaEngagementData,MediaEngagementBypassAutoplayPolicies",
]

_CHROME_EXTRA = [
    "--disable-infobars",
    "--disable-session-crashed-bubble",
    "--noerrdialogs",
]


def _get_monitors():
    try:
        from screeninfo import get_monitors

        return get_monitors()
    except Exception:
        class _M:
            x, y, width, height = 0, 0, 1920, 1080

        return [_M()]


def _profile_dir(browser_id: str, kind: str = "kiosk") -> str:
    base = Path(tempfile.gettempdir()) / f"eumbang-{browser_id}-{kind}"
    base.mkdir(parents=True, exist_ok=True)
    return str(base)


def _edge_paths() -> list[Path]:
    pf = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    pfx86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    return [
        pf / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        pfx86 / "Microsoft" / "Edge" / "Application" / "msedge.exe",
    ]


def _chrome_paths() -> list[str]:
    found: list[str] = []
    pf = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    pfx86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    for p in (
        pf / "Google" / "Chrome" / "Application" / "chrome.exe",
        pfx86 / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
    ):
        if p.is_file():
            found.append(str(p))
    for name in ("chrome", "google-chrome"):
        w = shutil.which(name)
        if w and w not in found:
            found.append(w)
    return found


def find_edge_for_kiosk() -> str | None:
    """방송 키오스크용 — 설치된 Microsoft Edge만 (WebView2 런타임 exe 제외)."""
    for p in _edge_paths():
        if p.is_file():
            return str(p)
    return None


def find_edge() -> str | None:
    exe = find_edge_for_kiosk()
    if exe:
        return exe
    try:
        from webview2_runtime import find_bundled_browser_exe

        bundled = find_bundled_browser_exe()
        if bundled:
            return bundled
    except Exception:
        pass
    return None


def find_chrome() -> str | None:
    paths = _chrome_paths()
    return paths[0] if paths else None


def list_available_browsers() -> dict[str, bool]:
    return {"edge": find_edge() is not None, "chrome": find_chrome() is not None}


def resolve_browser_exe(preference: str | None = None) -> tuple[str, str] | None:
    pref = (preference or "auto").lower().strip()
    edge = find_edge_for_kiosk() or find_edge()
    chrome = find_chrome()
    if pref == "edge":
        if edge:
            return edge, "edge"
        if chrome:
            return chrome, "chrome"
        return None
    if pref == "chrome":
        if chrome:
            return chrome, "chrome"
        if edge:
            return edge, "edge"
        return None
    if edge:
        return edge, "edge"
    if chrome:
        return chrome, "chrome"
    return None


def _show_broadcast_error(msg: str) -> None:
    get_logger().error("broadcast: %s", msg.replace("\n", " | "))
    print(f"[{APP_NAME}] {msg}", file=sys.stderr)
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, msg, APP_NAME, 0x10)
        except Exception:
            pass


def _is_bundled_edge(exe: str) -> bool:
    try:
        from webview2_runtime import find_bundled_browser_exe

        bundled = find_bundled_browser_exe()
        return bool(bundled and Path(exe).resolve() == Path(bundled).resolve())
    except Exception:
        return False


def _build_browser_args(
    exe: str, browser_id: str, url: str, m, *, profile_kind: str = "kiosk"
) -> list[str]:
    """
    Chrome: --app 과 --kiosk 를 같이 쓰면 전체화면이 깨지므로 URL을 직접 넘김.
    """
    common = [
        f"--user-data-dir={_profile_dir(browser_id, profile_kind)}",
        "--no-first-run",
        "--no-default-browser-check",
        *_CHROMIUM_AUTOPLAY_FLAGS,
        f"--window-position={m.x},{m.y}",
        f"--window-size={m.width},{m.height}",
    ]

    if browser_id == "chrome":
        return [
            exe,
            *common,
            *_CHROME_EXTRA,
            "--kiosk",
            "--start-fullscreen",
            url,
        ]

    # Edge 또는 번들 msedgewebview2.exe
    edge_args = [
        exe,
        *common,
        "--kiosk",
        "--start-fullscreen",
        url,
    ]
    if not _is_bundled_edge(exe):
        edge_args.insert(-1, "--edge-kiosk-type=fullscreen")
    return edge_args


def _launch_kiosk_browser(
    url: str,
    display_index: int,
    *,
    profile_kind: str = "kiosk",
) -> subprocess.Popen | None:
    cfg = load_config()
    pref = cfg.get("broadcast_browser", "auto")
    resolved = resolve_browser_exe(pref)

    if not resolved:
        _show_broadcast_error(
            "방송 브라우저를 찾을 수 없습니다.\n\n"
            "exe 안에 WebView2가 포함되지 않았거나\n"
            "첫 실행 시 런타임 풀기에 실패했습니다.\n"
            "build.bat 으로 다시 빌드한 exe를 사용하세요."
        )
        return None

    exe, browser_id = resolved
    monitors = _get_monitors()
    idx = min(max(0, display_index), len(monitors) - 1)
    m = monitors[idx]
    args = _build_browser_args(exe, browser_id, url, m, profile_kind=profile_kind)

    try:
        proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        name = "Microsoft Edge" if browser_id == "edge" else "Google Chrome"
        get_logger().info(
            "kiosk started browser=%s pid=%s display=%s profile=%s url=%s",
            name,
            proc.pid,
            idx,
            profile_kind,
            url,
        )
        return proc
    except OSError as exc:
        _show_broadcast_error(f"방송 창 실행 실패:\n{exc}")
        return None


def _open_browser_kiosk(url: str, display_index: int) -> None:
    global _browser_proc
    close_broadcast_window()

    proc = _launch_kiosk_browser(url, display_index, profile_kind="kiosk")
    if proc:
        _browser_proc = proc
        print(f"[{APP_NAME}] 방송 창: 전체화면 키오스크")


def open_broadcast_window(display_index: int, port: int) -> None:
    url = f"http://127.0.0.1:{port}/broadcast/?kiosk=1"
    _open_browser_kiosk(url, display_index)


def get_broadcast_pid() -> int | None:
    global _browser_proc
    if _browser_proc is None:
        return None
    try:
        return int(_browser_proc.pid)
    except Exception:
        return None


def open_external_youtube_video(video_id: str, display_index: int = 0) -> None:
    """임베드 불가 YouTube — watch 페이지를 별도 키오스크 창에서 재생."""
    global _external_yt_proc
    close_external_youtube()
    vid = (video_id or "").strip()
    if not vid:
        return
    url = f"https://www.youtube.com/watch?v={vid}"
    proc = _launch_kiosk_browser(url, display_index, profile_kind="external-yt")
    if proc:
        _external_yt_proc = proc
        get_logger().info("external youtube playback video_id=%s", vid)


def get_external_youtube_pid() -> int | None:
    global _external_yt_proc
    if _external_yt_proc is None:
        return None
    try:
        return int(_external_yt_proc.pid)
    except Exception:
        return None


def external_youtube_running() -> bool:
    global _external_yt_proc
    if _external_yt_proc is None:
        return False
    try:
        return _external_yt_proc.poll() is None
    except Exception:
        return False


def close_external_youtube() -> None:
    global _external_yt_proc
    if _external_yt_proc is not None:
        try:
            _external_yt_proc.terminate()
            _external_yt_proc.wait(timeout=3)
        except Exception:
            try:
                _external_yt_proc.kill()
            except Exception:
                pass
        get_logger().info("external youtube window closed")
        _external_yt_proc = None


def close_broadcast_window() -> None:
    global _browser_proc
    close_external_youtube()

    if _browser_proc is not None:
        try:
            _browser_proc.terminate()
            _browser_proc.wait(timeout=3)
        except Exception:
            try:
                _browser_proc.kill()
            except Exception:
                pass
        get_logger().info("broadcast window closed")
        _browser_proc = None


