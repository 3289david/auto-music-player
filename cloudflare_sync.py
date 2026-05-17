"""Cloudflare D1 sync — push/pull playlist & settings between app and DB."""
from __future__ import annotations

import json
import threading
from typing import Any

import urllib.request
import urllib.error

import logging
from panel_log import get_logger

log = logging.getLogger(__name__)

_token_cache: dict[str, str] = {}
_token_lock = threading.Lock()


def _api_url(cfg: dict[str, Any], path: str) -> str:
    base = cfg.get("cloudflare_worker_url", "").rstrip("/")
    return f"{base}{path}"


def _get_token(cfg: dict[str, Any]) -> str | None:
    """Login and cache a JWT token."""
    with _token_lock:
        cached = _token_cache.get("token")
        if cached:
            return cached

    url = _api_url(cfg, "/api/auth/login")
    payload = json.dumps({
        "username": cfg.get("cf_username", "admin"),
        "password": cfg.get("cf_password", "1234"),
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
            return token
    except Exception as e:
        log.warning("CF auth failed: %s", e)
    return None


def _clear_token() -> None:
    with _token_lock:
        _token_cache.clear()


def _request(cfg: dict[str, Any], method: str, path: str, body: Any = None) -> dict[str, Any] | None:
    token = _get_token(cfg)
    if not token:
        return None
    url = _api_url(cfg, path)
    payload = json.dumps(body).encode() if body is not None else None
    headers: dict[str, str] = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    try:
        req = urllib.request.Request(url, data=payload, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            _clear_token()
        log.warning("CF request %s %s → HTTP %s", method, path, e.code)
    except Exception as e:
        log.warning("CF request %s %s failed: %s", method, path, e)
    return None


def is_configured(cfg: dict[str, Any]) -> bool:
    """Returns True only if the Worker URL is set."""
    return bool(cfg.get("cloudflare_worker_url", "").strip())


# ─── Public API ──────────────────────────────────────────────────────────────

def push(cfg: dict[str, Any], playlist: list[dict], settings: dict) -> bool:
    """Push local playlist + settings to Cloudflare D1."""
    if not is_configured(cfg):
        log.info("CF sync not configured — skipping push")
        return False
    result = _request(cfg, "POST", "/api/sync/push", {
        "playlist": playlist,
        "settings": settings,
    })
    ok = result is not None and result.get("ok")
    if ok:
        log.info("CF push OK — %s songs, pushed_at=%s", len(playlist), result.get("pushed_at"))
    else:
        log.warning("CF push failed or returned unexpected result: %s", result)
    return ok


def pull(cfg: dict[str, Any]) -> tuple[list[dict], dict] | tuple[None, None]:
    """Pull playlist + settings from Cloudflare D1. Returns (playlist, settings) or (None, None)."""
    if not is_configured(cfg):
        log.info("CF sync not configured — skipping pull")
        return None, None
    result = _request(cfg, "GET", "/api/sync/pull")
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
