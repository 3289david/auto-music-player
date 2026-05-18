"""앱 단일 실행 (Windows Mutex)."""
from __future__ import annotations

import sys

from app_meta import APP_NAME

_MUTEX_NAME = "Global\\Eumbang2ndGen_SingleInstance_v1"


def ensure_single_instance() -> None:
    """이미 실행 중이면 메시지 후 종료."""
    if sys.platform != "win32":
        return

    import ctypes

    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32

    kernel32.CreateMutexW(None, True, _MUTEX_NAME)
    already = kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS

    if already:
        user32.MessageBoxW(
            None,
            f"{APP_NAME}이(가) 이미 실행 중입니다.\n작업 표시줄 트레이를 확인하세요.",
            APP_NAME,
            0x40,
        )
        sys.exit(0)
