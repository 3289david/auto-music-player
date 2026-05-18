"""Windows: 방송 시작 시 다른 창 최소화, 방송 창 포커스."""
from __future__ import annotations

import sys
import time

if sys.platform != "win32":

    def minimize_other_windows(keep_hwnds: set[int] | None = None) -> None:
        return

    def focus_process_main_window(pid: int, timeout: float = 12.0) -> int | None:
        return None

else:
    import ctypes
    import win32con
    import win32gui
    import win32process

    _SKIP_CLASSES = frozenset(
        {
            "Shell_TrayWnd",
            "Shell_SecondaryTrayWnd",
            "Progman",
            "WorkerW",
            "DV2ControlHost",
            "ForegroundStaging",
            "Windows.UI.Core.CoreWindow",
        }
    )

    def minimize_other_windows(keep_hwnds: set[int] | None = None) -> None:
        keep = {int(h) for h in (keep_hwnds or set()) if h}
        own_pid = win32process.GetCurrentProcessId()

        def enum_cb(hwnd: int, _: None) -> bool:
            try:
                if hwnd in keep:
                    return True
                if not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd):
                    return True
                if win32gui.GetWindow(hwnd, win32con.GW_OWNER):
                    return True
                ex = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
                if ex & win32con.WS_EX_TOOLWINDOW:
                    return True
                if win32gui.GetClassName(hwnd) in _SKIP_CLASSES:
                    return True
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid == own_pid and hwnd in keep:
                    return True
                win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
            except Exception:
                pass
            return True

        win32gui.EnumWindows(enum_cb, None)

    def _find_main_window_for_pid(pid: int) -> int | None:
        best: int | None = None
        best_area = 0

        def enum_cb(hwnd: int, _: None) -> bool:
            nonlocal best, best_area
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    return True
                if win32gui.GetWindow(hwnd, win32con.GW_OWNER):
                    return True
                _, wpid = win32process.GetWindowThreadProcessId(hwnd)
                if wpid != pid:
                    return True
                left, top, right, bottom = win32gui.GetWindowRect(hwnd)
                area = max(0, right - left) * max(0, bottom - top)
                if area > best_area:
                    best_area = area
                    best = hwnd
            except Exception:
                pass
            return True

        win32gui.EnumWindows(enum_cb, None)
        return best

    def focus_process_main_window(pid: int, timeout: float = 12.0) -> int | None:
        user32 = ctypes.windll.user32
        HWND_TOPMOST = -1
        HWND_NOTOPMOST = -2
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_SHOWWINDOW = 0x0040

        deadline = time.time() + timeout
        hwnd: int | None = None
        while time.time() < deadline:
            hwnd = _find_main_window_for_pid(pid)
            if hwnd:
                break
            time.sleep(0.25)
        if not hwnd:
            return None

        try:
            user32.AllowSetForegroundWindow(pid)
        except Exception:
            pass
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
            win32gui.SetWindowPos(
                hwnd,
                HWND_TOPMOST,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW,
            )
            win32gui.SetForegroundWindow(hwnd)
            win32gui.SetWindowPos(
                hwnd,
                HWND_NOTOPMOST,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW,
            )
        except Exception:
            try:
                win32gui.SetForegroundWindow(hwnd)
            except Exception:
                pass
        return hwnd
