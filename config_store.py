"""config.json 로드·저장 (exe 빌드 시 실행 파일 옆에 데이터 저장)."""
from __future__ import annotations

import json
import secrets
import sys
from pathlib import Path
from typing import Any

DEFAULT_PORT = 8765
ALLOWED_UPLOAD_EXT = {".mp4", ".mkv", ".mp3", ".wav", ".m4a", ".webm", ".ogg", ".flac"}


def get_install_dir() -> Path:
    """설정·업로드 등 쓰기 가능 경로 (exe와 같은 폴더)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_bundle_dir() -> Path:
    """패널/방송 HTML 등 번들 리소스 (PyInstaller _MEIPASS)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", get_install_dir()))
    return Path(__file__).resolve().parent


INSTALL_DIR = get_install_dir()
BUNDLE_DIR = get_bundle_dir()

CONFIG_PATH = INSTALL_DIR / "config.json"
UPLOADS_DIR = INSTALL_DIR / "uploads"
ASSETS_DIR = INSTALL_DIR / "assets"


def ensure_dirs() -> None:
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)


CF_DEFAULTS: dict[str, Any] = {
    "cloudflare_worker_url": "https://auto-music-player-backend.rukkit.workers.dev",
    "cf_username": "admin",
    "cf_password": "1234",
    "cf_auto_pull_on_start": True,   # pull from DB when app launches
    "cf_auto_push_on_stop": False,   # push to DB when app closes (opt-in)
}


def load_config() -> dict[str, Any]:
    ensure_dirs()
    if not CONFIG_PATH.exists():
        cfg = {
            "secret_key": secrets.token_hex(32),
            "admin_username": "",
            "password_hash": "",
            "port": DEFAULT_PORT,
            "end_broadcast_image": "",
            "autostart": False,
            "broadcast_browser": "auto",
            "onboarding_complete": False,
            **CF_DEFAULTS,
        }
        save_config(cfg)
        return cfg
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not data.get("secret_key"):
        data["secret_key"] = secrets.token_hex(32)
        save_config(data)
    if "onboarding_complete" not in data and is_setup_complete(data):
        data["onboarding_complete"] = True
        save_config(data)
    # Inject CF defaults for existing configs missing them
    changed = False
    for k, v in CF_DEFAULTS.items():
        if k not in data:
            data[k] = v
            changed = True
    if changed:
        save_config(data)
    return data


def save_config(data: dict[str, Any]) -> None:
    ensure_dirs()
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_setup_complete(cfg: dict[str, Any]) -> bool:
    return bool(cfg.get("admin_username") and cfg.get("password_hash"))
