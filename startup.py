"""Windows 시작 프로그램 등록."""
from __future__ import annotations

import sys
from pathlib import Path

from app_meta import APP_SHORT
from config_store import get_install_dir

APP_NAME = APP_SHORT


def _run_command() -> str:
    install = get_install_dir()
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable)
        return f'"{exe}"'
    main_py = install / "main.py"
    return f'"{sys.executable}" "{main_py}"'


def is_autostart_enabled() -> bool:
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_READ,
        )
        try:
            winreg.QueryValueEx(key, APP_NAME)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except OSError:
        return False


def set_autostart(enabled: bool) -> None:
    import winreg

    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        0,
        winreg.KEY_SET_VALUE,
    )
    try:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _run_command())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
    finally:
        winreg.CloseKey(key)
