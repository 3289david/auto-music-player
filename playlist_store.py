"""플레이리스트 영속 저장 (playlist.json)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config_store import INSTALL_DIR

PLAYLIST_PATH = INSTALL_DIR / "playlist.json"


def load_playlist() -> list[dict[str, Any]]:
    if not PLAYLIST_PATH.exists():
        return []
    try:
        with PLAYLIST_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return []


def save_playlist(items: list[dict[str, Any]]) -> None:
    PLAYLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PLAYLIST_PATH.open("w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
