"""패널/앱 진단 로그 — %LOCALAPPDATA%\\3세대음방시스템\\logs\\"""
from __future__ import annotations

import logging
import os
import sys
import tempfile
import threading
import traceback
from pathlib import Path

from app_meta import EXE_NAME

_LOG_DIR = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / EXE_NAME / "logs"
_PANEL_LOG = _LOG_DIR / "panel.log"
_CRASH_LOG = _LOG_DIR / "crash.log"
_logger: logging.Logger | None = None
_installed = False


def log_dir() -> Path:
    return _LOG_DIR


def panel_log_path() -> Path:
    return _PANEL_LOG


def setup_panel_logging() -> logging.Logger:
    global _logger
    if _logger is not None:
        return _logger

    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    _logger = logging.getLogger("eumbang")
    _logger.setLevel(logging.DEBUG)
    _logger.propagate = False

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    fh = logging.FileHandler(_PANEL_LOG, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)
    _logger.addHandler(fh)

    if not getattr(sys, "frozen", False):
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        sh.setLevel(logging.INFO)
        _logger.addHandler(sh)

    _logger.info("=== 로그 시작 ===")
    _logger.info("python=%s frozen=%s", sys.version.split()[0], getattr(sys, "frozen", False))
    _logger.info("log_file=%s", _PANEL_LOG)
    return _logger


def get_logger() -> logging.Logger:
    return setup_panel_logging()


def install_crash_logging() -> None:
    global _installed
    if _installed:
        return
    _installed = True

    log = setup_panel_logging()
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    try:
        import faulthandler

        crash_fp = open(_CRASH_LOG, "a", encoding="utf-8")
        faulthandler.enable(file=crash_fp, all_threads=True)
        log.info("faulthandler → %s", _CRASH_LOG)
    except Exception as exc:
        log.warning("faulthandler 비활성: %s", exc)

    def _excepthook(exc_type, exc, tb):
        log.critical("처리되지 않은 예외", exc_info=(exc_type, exc, tb))
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _excepthook

    def _thread_hook(args: threading.ExceptHookArgs) -> None:
        log.critical(
            "스레드 예외 thread=%s",
            getattr(args.thread, "name", "?"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    threading.excepthook = _thread_hook
    log.info("crash hooks installed")


def log_exception(msg: str) -> None:
    get_logger().error("%s\n%s", msg, traceback.format_exc())
