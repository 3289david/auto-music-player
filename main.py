"""
3세대 음방시스템 진입점.
방송 PC: 네이티브 패널(iframe) + 트레이 | 단일 실행
"""
from __future__ import annotations

import os
import queue
import sys
import threading
import time

import cloudflare_sync
from app_icon_util import apply_windows_app_identity, ensure_app_icon_ico
from panel_log import install_crash_logging, panel_log_path, setup_panel_logging
from webview2_runtime import configure_bundled_webview2
from app_meta import APP_NAME
from broadcast_window import close_broadcast_window
from config_store import load_config
from network_utils import panel_urls
from panel_window import run_panel_native, stop_panel_window
from playlist_store import load_playlist, save_playlist
from server import auto_setup_admin, broadcast_state, create_socketio_app, set_broadcast_queue, start_server_thread
from single_instance import ensure_single_instance
from tray_icon import start_tray_thread, stop_tray

_command_queue: queue.Queue = queue.Queue()
_shutting_down = False


def _process_commands(port: int) -> None:
    while not _shutting_down:
        try:
            cmd = _command_queue.get(timeout=0.15)
        except queue.Empty:
            continue
        action = cmd.get("action")
        if action == "open_broadcast":
            from broadcast_window import get_broadcast_pid, open_broadcast_window
            from panel_window import enqueue_panel_window_command
            from win_desktop import focus_process_main_window, minimize_other_windows

            display_index = int(cmd.get("display_index", 0))
            enqueue_panel_window_command("minimize")
            time.sleep(0.25)
            minimize_other_windows(set())
            open_broadcast_window(display_index, port)
            pid = get_broadcast_pid()
            if pid:
                threading.Thread(
                    target=focus_process_main_window,
                    args=(pid,),
                    daemon=True,
                ).start()
        elif action == "close_broadcast":
            close_broadcast_window()


def _command_worker(port: int) -> None:
    while not _shutting_down:
        _process_commands(port)
        time.sleep(0.05)


def _shutdown() -> None:
    global _shutting_down
    _shutting_down = True
    stop_panel_window()
    close_broadcast_window()
    stop_tray()
    os._exit(0)


def main() -> None:
    install_crash_logging()
    setup_panel_logging().info("main() start log=%s", panel_log_path())
    apply_windows_app_identity()
    ensure_app_icon_ico()
    configure_bundled_webview2()

    # Auto-create admin/1234 account — skip onboarding entirely
    auto_setup_admin()

    cfg = load_config()
    port = int(cfg.get("port", 8765))

    set_broadcast_queue(_command_queue)
    create_socketio_app(cfg)

    start_server_thread(port)
    time.sleep(1.0)

    threading.Thread(target=_command_worker, args=(port,), daemon=True).start()

    # Auto-pull playlist & settings from Cloudflare D1 on startup
    if cfg.get("cf_auto_pull_on_start", True) and cloudflare_sync.is_configured(cfg):
        def _on_pull(pl, settings):
            broadcast_state.set_playlist(pl)
            save_playlist(pl)
            setup_panel_logging().info("CF auto-pull: %d songs loaded from D1", len(pl))
        cloudflare_sync.pull_background(cfg, _on_pull)

    urls = panel_urls(port)
    panel_addr = urls["primary_lan"] or urls["local"]
    if not getattr(sys, "frozen", False):
        print("=" * 50)
        print(f"{APP_NAME} 실행 중 (단일 실행)")
        print(f"  패널(WebView2): {panel_addr}")
        for lan in urls["lan"]:
            print(f"  다른 기기: {lan}")
        print("=" * 50)

    start_tray_thread(port, _shutdown, native_panel=True)

    # 패널 메시지 루프는 메인 스레드에서 블로킹 (종료 시 stop_panel_window → WM_QUIT)
    if not run_panel_native(port):
        sys.exit(1)


if __name__ == "__main__":
    ensure_single_instance()
    try:
        main()
    except KeyboardInterrupt:
        _shutdown()
