"""Cloudflare D1 sync — push/pull playlist & settings between app and DB."""
from __future__ import annotations

import json
import threading
from typing import Any

import urllib.request
import urllib.error
import logging

log = logging.getLogger(__name__)

# ── 하드코딩된 Worker 정보 (설정 불필요) ─────────────────────────────────────
WORKER_URL  = "https://auto-music-player-backend.rukkit.workers.dev"
CF_USERNAME = "admin"
CF_PASSWORD = "1234"

_token_cache: dict[str, str] = {}
_token_lock = threading.Lock()


def _api_url(path: str) -> str:
    return f"{WORKER_URL}{path}"


def _get_token() -> str | None:
    """Login and cache a JWT token."""
    with _token_lock:
        cached = _token_cache.get("token")
        if cached:
            return cached

    url = _api_url("/api/auth/login")
    payload = json.dumps({
        "username": CF_USERNAME,
        "password": CF_PASSWORD,
    }).encode()
    try:
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        token = data.get("token")
        if token:
            with _token_lock:
                _token_cache["token"] = token
            log.info("CF auth OK — token acquired")
            return token
        log.warning("CF auth: no token in response: %s", data)
    except Exception as e:
        log.warning("CF auth failed: %s", e)
    return None


def _clear_token() -> None:
    with _token_lock:
        _token_cache.clear()


def _request(method: str, path: str, body: Any = None) -> dict[str, Any] | None:
    token = _get_token()
    if not token:
        log.warning("CF request skipped — no token")
        return None
    url = _api_url(path)
    payload = json.dumps(body).encode() if body is not None else None
    headers: dict[str, str] = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    try:
        req = urllib.request.Request(url, data=payload, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            log.info("CF %s %s → OK", method, path)
            return result
    except urllib.error.HTTPError as e:
        body_text = e.read().decode(errors="replace") if hasattr(e, "read") else ""
        log.warning("CF request %s %s → HTTP %s: %s", method, path, e.code, body_text)
        if e.code == 401:
            _clear_token()
    except Exception as e:
        log.warning("CF request %s %s failed: %s", method, path, e)
    return None


def is_configured(_cfg: Any = None) -> bool:
    """Always configured — Worker URL is hardcoded."""
    return True


# ─── Public API ──────────────────────────────────────────────────────────────

def push(cfg: dict[str, Any], playlist: list[dict], settings: dict) -> bool:
    """Push local playlist + settings to Cloudflare D1."""
    result = _request("POST", "/api/sync/push", {
        "playlist": playlist,
        "settings": settings,
    })
    ok = result is not None and result.get("ok")
    if ok:
        log.info("CF push OK — %s songs, pushed_at=%s", len(playlist), result.get("pushed_at"))
    else:
        log.warning("CF push failed: %s", result)
    return ok


def pull(cfg: dict[str, Any]) -> tuple[list[dict], dict] | tuple[None, None]:
    """Pull playlist + settings from Cloudflare D1. Returns (playlist, settings) or (None, None)."""
    result = _request("GET", "/api/sync/pull")
    if result is None:
        return None, None
    pl = result.get("playlist") or []
    settings = result.get("settings") or {}
    log.info("CF pull OK — %s songs, pulled_at=%s", len(pl), result.get("pulled_at"))
    return pl, settings


def push_background(cfg: dict[str, Any], playlist: list[dict], settings: dict) -> None:
    """Non-blocking fire-and-forget push."""
    threading.Thread(
        target=push,
        args=(cfg, playlist, settings),
        daemon=True,
        name="cf-push",
    ).start()


def pull_background(cfg: dict[str, Any], callback) -> None:
    """Non-blocking pull; calls callback(playlist, settings) on the result."""
    def _run():
        pl, settings = pull(cfg)
        if pl is not None:
            callback(pl, settings)
    threading.Thread(target=_run, daemon=True, name="cf-pull").start()
