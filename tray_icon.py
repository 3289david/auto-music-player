"""Windows 시스템 트레이 아이콘."""
from __future__ import annotations

import threading
from typing import Callable

from app_icon_util import load_tray_image
from app_meta import APP_NAME

_icon = None
_port: int = 8765


def _open_panel(_icon, _item=None):
    from panel_window import focus_panel_window

    focus_panel_window()


def run_tray(port: int, on_quit: Callable[[], None], native_panel: bool = False) -> None:
    import pystray

    global _icon, _port
    _port = port

    def quit_app(icon, _item=None):
        icon.visible = False
        icon.stop()
        on_quit()

    menu = pystray.Menu(
        pystray.MenuItem("컨트롤 패널 보기", _open_panel, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("종료", quit_app),
    )

    _icon = pystray.Icon(
        APP_NAME,
        load_tray_image(),
        f"{APP_NAME} — 실행 중",
        menu,
    )

    try:
        _icon.notify("패널 창에서 제어하세요.", APP_NAME)
    except Exception:
        pass

    _icon.run()


def start_tray_thread(port: int, on_quit: Callable[[], None], native_panel: bool) -> None:
    threading.Thread(
        target=run_tray,
        args=(port, on_quit, native_panel),
        daemon=True,
        name="eumbang-tray",
    ).start()


def stop_tray() -> None:
    global _icon
    if _icon is not None:
        try:
            _icon.stop()
        except Exception:
            pass
        _icon = None
