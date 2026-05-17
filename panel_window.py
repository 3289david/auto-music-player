"""
방송 PC — 컨트롤 패널 (Windows WebView2).

창 버튼(최소/최대/닫기)은 WebView2 API 대신 HTTP → 큐 → 메인 메시지 루프에서 Win32 처리.
"""
from __future__ import annotations

import asyncio
import os
import queue
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from app_icon_util import ensure_app_icon_ico
from app_meta import APP_NAME
from network_utils import panel_urls
from panel_log import get_logger, log_exception, panel_log_path, setup_panel_logging
from webview2_runtime import configure_bundled_webview2, runtime_status_message

log = get_logger

_PANEL_WINDOW = None
_lock = threading.Lock()
_panel_stop = threading.Event()
_panel_started = False
_panel_cmd_queue: queue.Queue[str] = queue.Queue()

_PANEL_ASPECT_W = 16
_PANEL_ASPECT_H = 9
_PANEL_SCREEN_FRACTION = 0.98
_PANEL_MIN_WIDTH = 1360
_PANEL_MAX_WIDTH = 2200
_PANEL_MIN_HEIGHT = 1080

_CMD_MINIMIZE = "minimize"
_CMD_MAXIMIZE = "maximize"
_CMD_RESTORE = "restore"
_CMD_HIDE = "hide"
_CMD_SHOW = "show"


def resolve_panel_url(port: int) -> str:
    return panel_urls(port)["local"]


def enqueue_panel_window_command(action: str) -> None:
    action = (action or "").strip().lower()
    if action not in (_CMD_MINIMIZE, _CMD_MAXIMIZE, _CMD_RESTORE, _CMD_HIDE, _CMD_SHOW):
        log().warning("unknown panel window cmd: %s", action)
        return
    _panel_cmd_queue.put(action)
    log().debug("queued panel cmd: %s (qsize~%s)", action, _panel_cmd_queue.qsize())


def _drain_panel_commands() -> list[str]:
    cmds: list[str] = []
    while True:
        try:
            cmds.append(_panel_cmd_queue.get_nowait())
        except queue.Empty:
            break
    return cmds


def _wait_for_server(panel_url: str, timeout_sec: float = 25.0) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            req = urllib.request.Request(panel_url, method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status < 500:
                    return True
        except (urllib.error.URLError, OSError, TimeoutError):
            pass
        time.sleep(0.35)
    return False


def _show_fatal(msg: str) -> None:
    log().error("fatal: %s", msg)
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                None,
                msg + f"\n\n로그 파일:\n{panel_log_path()}",
                APP_NAME,
                0x10,
            )
        except Exception:
            pass
    print(f"[{APP_NAME}] {msg}", file=sys.stderr)


def _panel_geometry() -> tuple[int, int, int, int]:
    width = 1580
    height = max(_PANEL_MIN_HEIGHT, int(width * _PANEL_ASPECT_H / _PANEL_ASPECT_W))
    x, y = 0, 0
    if sys.platform != "win32":
        return width, height, x, y
    try:
        import win32api
        import win32con

        monitor = win32api.MonitorFromPoint((0, 0), win32con.MONITOR_DEFAULTTOPRIMARY)
        info = win32api.GetMonitorInfo(monitor)
        work = info["Work"]
        wa_w = work[2] - work[0]
        wa_h = work[3] - work[1]
        margin = 40

        width = int(wa_w * _PANEL_SCREEN_FRACTION)
        width = max(_PANEL_MIN_WIDTH, min(_PANEL_MAX_WIDTH, width))
        height = max(_PANEL_MIN_HEIGHT, int(width * _PANEL_ASPECT_H / _PANEL_ASPECT_W))

        max_h = wa_h - margin
        if height > max_h:
            height = max(min(_PANEL_MIN_HEIGHT, max_h), max_h)
            width = int(height * _PANEL_ASPECT_W / _PANEL_ASPECT_H)

        max_w = wa_w - margin
        if width > max_w:
            width = max(640, max_w)
            height = max(_PANEL_MIN_HEIGHT, int(width * _PANEL_ASPECT_H / _PANEL_ASPECT_W))

        x = work[0] + (wa_w - width) // 2
        y = work[1] + (wa_h - height) // 2
    except Exception:
        log().warning("geometry fallback", exc_info=True)
    return width, height, x, y


def _apply_panel_geometry(hwnd: int) -> None:
    """창 크기·위치를 작업 영역 중앙에 맞춤 (dll.set_position 보완)."""
    if sys.platform != "win32" or not hwnd:
        return
    try:
        import win32con
        import win32gui

        w, h, x, y = _panel_geometry()
        win32gui.SetWindowPos(
            hwnd,
            None,
            x,
            y,
            w,
            h,
            win32con.SWP_NOZORDER,
        )
        log().info("panel centered %sx%s @ %s,%s", w, h, x, y)
    except Exception:
        log().warning("center panel hwnd failed", exc_info=True)


def _patch_webview2_transport(loop: asyncio.AbstractEventLoop) -> None:
    """DLL 콜백 스레드에서 asyncio.create_task 호출 시 크래시 방지."""
    import json

    import voxe
    from webview2 import bridge
    from webview2.base import dll

    if getattr(bridge.Transport, "_eumbang_safe_listen", False):
        return

    def _schedule(coro) -> None:
        def _runner() -> None:
            asyncio.ensure_future(coro, loop=loop)

        try:
            loop.call_soon_threadsafe(_runner)
        except RuntimeError:
            pass

    def safe_on_listen(self, buf: bytes) -> None:
        try:
            data = json.loads(buf)
            if "type" not in data:
                return
            if data["type"] == "ack":
                pkgid = data["pkgid"]
                if pkgid in self.acks:
                    loop.call_soon_threadsafe(self.acks[pkgid].set_result, 1)
                return
            if data["type"] != "req":
                return
            self.pkgid = data["pkgid"]
            if self.reqid is None or self.reqid != data["reqid"]:
                self.reqid = data["reqid"]
                self.total = data["total"]
                self.cache = bytearray(self.total)
                self.offset = 0
            size = data["size"]
            self.cache[self.offset : self.offset + size] = self._read(size)
            dll.post(
                json.dumps(dict(type="ack", pkgid=self.pkgid, reqid=self.reqid)).encode(encoding="utf-8")
            )
            self.offset += size
            if self.offset >= self.total:
                try:
                    ctx = voxe.loads(bytes(self.cache))
                    method_name, args = ctx[0], ctx[1:]
                    if type(self.scopes) is dict:
                        if method_name in self.scopes:
                            r = self.scopes[method_name](*args)
                            _schedule(self.send(voxe.dumps(0, r), self.reqid))
                        else:
                            _schedule(self.send(voxe.dumps(1, "no such method"), self.reqid))
                    else:
                        if method_name in dir(self.scopes):
                            r = getattr(self.scopes, method_name)(*args)
                            _schedule(self.send(voxe.dumps(0, r), self.reqid))
                        else:
                            _schedule(self.send(voxe.dumps(1, "no such method"), self.reqid))
                except Exception as e:
                    log().error("api call failed", exc_info=True)
                    _schedule(self.send(voxe.dumps(1, str(e)), self.reqid))
                if self.on_service:
                    self.on_service(self.cache)
            if self.offset >= self.total and self.reqid in self.futures:
                fut = self.futures[self.reqid]
                result = bytes(self.cache)

                def _done(f=fut, v=result) -> None:
                    if not f.done():
                        f.set_result(v)

                loop.call_soon_threadsafe(_done)
                self.reqid = None
                self.cache = None
        except json.decoder.JSONDecodeError:
            pass
        except Exception:
            log().error("on_listen failed", exc_info=True)

    bridge.Transport.on_listen = safe_on_listen
    bridge.Transport._eumbang_safe_listen = True
    log().info("webview2 transport patched")


def _is_panel_hwnd(panel_hwnd: int, hwnd: int) -> bool:
    if not panel_hwnd or not hwnd:
        return False
    if hwnd == panel_hwnd:
        return True
    try:
        import win32con
        import win32gui

        return win32gui.GetAncestor(hwnd, win32con.GA_ROOT) == panel_hwnd
    except Exception:
        return False


def _make_panel_window_class():
    from webview2 import Window, webview2_api
    from webview2.base import dll

    class PanelWindow(Window):
        hwnd = None
        _maximized = False
        _normal_rect = None

        def __init__(self, title=None, icon=None, url=None, size=None, cache=None, memory_size=1024 * 1024 * 10):
            w, h, x, y = _panel_geometry()
            log().info("panel geometry %sx%s @ %s,%s", w, h, x, y)
            dll.set_size(w, h)
            dll.set_position(x, y)
            super().__init__(
                title=title,
                icon=icon,
                url=url,
                size=None,
                cache=cache,
                memory_size=memory_size,
            )

        @webview2_api
        def hide(self):
            enqueue_panel_window_command(_CMD_HIDE)

        @webview2_api
        def minimize(self):
            enqueue_panel_window_command(_CMD_MINIMIZE)

        @webview2_api
        def maximize(self):
            enqueue_panel_window_command(_CMD_MAXIMIZE)

        @webview2_api
        def restore(self):
            enqueue_panel_window_command(_CMD_RESTORE)

        @webview2_api
        def close(self):
            enqueue_panel_window_command(_CMD_HIDE)

        def _save_normal_rect(self) -> None:
            import win32gui

            if self.hwnd:
                self._normal_rect = win32gui.GetWindowRect(self.hwnd)

        def _apply_maximize(self) -> None:
            import win32api
            import win32con
            import win32gui

            if not self.hwnd:
                return
            self._save_normal_rect()
            monitor = win32api.MonitorFromWindow(self.hwnd, win32con.MONITOR_DEFAULTTONEAREST)
            work = win32api.GetMonitorInfo(monitor)["Work"]
            win32gui.SetWindowPos(
                self.hwnd,
                None,
                work[0],
                work[1],
                work[2] - work[0],
                work[3] - work[1],
                win32con.SWP_NOZORDER,
            )
            self._maximized = True
            log().info("maximized")

        def _apply_restore(self) -> None:
            import win32con
            import win32gui

            if not self.hwnd:
                return
            if self._normal_rect:
                left, top, right, bottom = self._normal_rect
                win32gui.SetWindowPos(
                    self.hwnd,
                    None,
                    left,
                    top,
                    right - left,
                    bottom - top,
                    win32con.SWP_NOZORDER,
                )
            else:
                win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
            self._maximized = False
            log().info("restored")

        def _run_window_command(self, cmd: str) -> None:
            import win32con
            import win32gui

            if not self.hwnd:
                log().warning("cmd %s but no hwnd", cmd)
                return
            log().info("exec window cmd: %s", cmd)
            try:
                if cmd == _CMD_MINIMIZE:
                    win32gui.PostMessage(self.hwnd, win32con.WM_SYSCOMMAND, win32con.SC_MINIMIZE, 0)
                elif cmd == _CMD_MAXIMIZE:
                    self._apply_maximize()
                elif cmd == _CMD_RESTORE:
                    self._apply_restore()
                elif cmd == _CMD_HIDE:
                    win32gui.ShowWindow(self.hwnd, win32con.SW_HIDE)
                elif cmd == _CMD_SHOW:
                    self.show()
            except Exception:
                log().error("cmd %s failed", cmd, exc_info=True)

        def _process_queued_commands(self) -> None:
            for cmd in _drain_panel_commands():
                try:
                    self._run_window_command(cmd)
                except Exception:
                    log().error("queue cmd failed: %s", cmd, exc_info=True)

        async def run(self):
            import pythoncom
            import win32con
            import win32gui
            import webview2 as wv2_pkg

            pythoncom.OleInitialize()
            try:
                _patch_webview2_transport(asyncio.get_running_loop())
                log().info("dll.build start")
                script_path = os.path.join(os.path.dirname(wv2_pkg.__file__), "webview2.js")
                dll.preload(self._build_context(script_path).encode("utf-8"))
                dll.build()
                self.hwnd = dll.get_window()
                log().info("hwnd=%s", self.hwnd)
                if self.hwnd:
                    _apply_panel_geometry(self.hwnd)
                    self.show()

                while not _panel_stop.is_set():
                    self._process_queued_commands()
                    r = win32gui.PeekMessage(None, 0, 0, win32con.PM_REMOVE)
                    code, msg = r
                    if code == 0:
                        await asyncio.sleep(0.005)
                        continue
                    hwnd, message, wparam = msg[0], msg[1], msg[2]
                    if message == win32con.WM_QUIT:
                        if _panel_stop.is_set():
                            log().info("WM_QUIT shutdown")
                            break
                        log().debug("WM_QUIT ignored")
                        continue
                    if self.hwnd and _is_panel_hwnd(self.hwnd, hwnd):
                        if message == win32con.WM_CLOSE:
                            log().debug("WM_CLOSE swallowed")
                            continue
                        if message == win32con.WM_SYSCOMMAND and (wparam & 0xFFF0) == win32con.SC_CLOSE:
                            log().debug("SC_CLOSE swallowed")
                            continue
                    try:
                        win32gui.TranslateMessage(msg)
                        win32gui.DispatchMessage(msg)
                    except Exception:
                        log().error("DispatchMessage failed msg=0x%x", message, exc_info=True)
            except Exception:
                log().critical("panel run() crashed", exc_info=True)
                raise
            finally:
                pythoncom.CoUninitialize()
                log().info("panel run() ended")

        def show(self):
            if not self.hwnd:
                return
            import win32con
            import win32gui

            win32gui.ShowWindow(self.hwnd, win32con.SW_SHOW)
            win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
            try:
                win32gui.SetForegroundWindow(self.hwnd)
            except Exception:
                pass
            log().debug("show()")

    return PanelWindow


def get_panel_hwnd() -> int | None:
    with _lock:
        win = _PANEL_WINDOW
    if win is None:
        return None
    hwnd = getattr(win, "hwnd", None)
    return int(hwnd) if hwnd else None


def focus_panel_window() -> None:
    global _PANEL_WINDOW
    log().info("focus_panel_window")
    enqueue_panel_window_command(_CMD_SHOW)
    with _lock:
        win = _PANEL_WINDOW
    if win is not None and hasattr(win, "show"):
        try:
            win.show()
        except Exception:
            log().error("focus show failed", exc_info=True)


def stop_panel_window() -> None:
    global _PANEL_WINDOW
    log().info("stop_panel_window")
    _panel_stop.set()
    with _lock:
        win = _PANEL_WINDOW
    if win and win.hwnd:
        try:
            import win32con
            import win32gui

            win32gui.PostMessage(win.hwnd, win32con.WM_QUIT, 0, 0)
        except Exception:
            log().error("stop WM_QUIT failed", exc_info=True)


def _run_panel_loop(panel_url: str, icon_path: Path | None) -> bool:
    global _PANEL_WINDOW, _panel_started

    PanelWindow = _make_panel_window_class()
    icon_arg = str(icon_path) if icon_path and icon_path.is_file() else None
    win = PanelWindow(title=APP_NAME, icon=icon_arg, url=panel_url)
    with _lock:
        _PANEL_WINDOW = win
    try:
        asyncio.run(win.run())
        return True
    except Exception as exc:
        log_exception(f"패널 루프 예외: {exc}")
        _show_fatal(f"패널 창 오류:\n{exc}\n\n로그: {panel_log_path()}")
        return False
    finally:
        with _lock:
            if _PANEL_WINDOW is win:
                _PANEL_WINDOW = None


def panel_native_available() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import webview2  # noqa: F401

        return True
    except ImportError:
        return False


def run_panel_native(port: int, on_closed: Callable[[], None] | None = None) -> bool:
    global _panel_started

    setup_panel_logging()
    log().info("run_panel_native port=%s", port)

    if sys.platform != "win32":
        _show_fatal("컨트롤 패널은 Windows 전용입니다.")
        return False

    try:
        import webview2  # noqa: F401
    except ImportError:
        _show_fatal("WebView2 패널 모듈이 없습니다.\n\nbuild.bat 으로 다시 빌드하세요.")
        return False

    if not configure_bundled_webview2():
        import sys as _sys
        if getattr(_sys, "frozen", False):
            # Compiled exe — bundled runtime is required
            _show_fatal("WebView2 런타임이 없습니다.\n\n" + runtime_status_message())
            return False
        # Dev mode — warn and continue (system Edge/WebView2 runtime will be used)
        log().warning("Bundled WebView2 runtime not found — falling back to system runtime (dev mode)")

    panel_url = resolve_panel_url(port)
    if not _wait_for_server(panel_url):
        _show_fatal(f"서버에 연결할 수 없습니다.\n{panel_url}")
        return False

    if _panel_started:
        focus_panel_window()
        return True

    _panel_stop.clear()
    _panel_started = True
    icon_path = ensure_app_icon_ico()
    return _run_panel_loop(panel_url, icon_path)


def open_panel_fallback(port: int) -> None:
    _show_fatal("브라우저로 열지 않습니다. webview2 패키지를 설치하세요.")
