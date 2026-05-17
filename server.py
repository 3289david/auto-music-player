"""Flask + SocketIO 서버."""
from __future__ import annotations

import queue
import secrets
import threading
import time
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from typing import Any, Callable

import bcrypt
from flask import (
    Flask,
    jsonify,
    redirect,
    render_template_string,
    request,
    session,
    url_for,
)
from flask_login import LoginManager, UserMixin, current_user, login_user, logout_user
from flask_socketio import SocketIO, disconnect, emit
from flask_wtf import CSRFProtect
from flask_wtf.csrf import generate_csrf
from werkzeug.utils import secure_filename

import cloudflare_sync
from config_store import (
    ALLOWED_UPLOAD_EXT,
    ASSETS_DIR,
    BUNDLE_DIR,
    UPLOADS_DIR,
    ensure_dirs,
    is_setup_complete,
    load_config,
    save_config,
)
from network_utils import panel_urls
from panel_log import get_logger
from panel_window import enqueue_panel_window_command
from playlist_store import load_playlist, save_playlist
from state import BroadcastState
from youtube_search import search_youtube
from youtube_util import fetch_youtube_video_meta, parse_youtube_video_id

# --- 전역 ---
broadcast_state = BroadcastState()
config_data: dict[str, Any] = {}
login_attempts: dict[str, dict[str, Any]] = {}
broadcast_command_queue: queue.Queue | None = None
_panel_sids: set[str] = set()
_panel_sids_lock = threading.Lock()

app = Flask(
    __name__,
    static_folder=str(BUNDLE_DIR / "panel" / "static"),
    static_url_path="/static",
    template_folder=str(BUNDLE_DIR / "panel"),
)
csrf = CSRFProtect()
login_manager = LoginManager()
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")


class AdminUser(UserMixin):
    def __init__(self, username: str):
        self.id = username


@login_manager.user_loader
def load_user(user_id: str) -> AdminUser | None:
    cfg = load_config()
    if user_id == cfg.get("admin_username"):
        return AdminUser(user_id)
    return None


def set_broadcast_queue(q: queue.Queue) -> None:
    global broadcast_command_queue
    broadcast_command_queue = q


def _client_ip() -> str:
    return request.headers.get("X-Forwarded-For", request.remote_addr or "127.0.0.1").split(",")[0].strip()


def _is_local_request() -> bool:
    ip = _client_ip()
    return ip in ("127.0.0.1", "::1", "localhost") or ip.startswith("127.")


def _register_panel_client() -> None:
    with _panel_sids_lock:
        _panel_sids.add(request.sid)


def _unregister_panel_client() -> None:
    with _panel_sids_lock:
        _panel_sids.discard(request.sid)


def _panel_sids_snapshot() -> list[str]:
    with _panel_sids_lock:
        return list(_panel_sids)


def _disconnect_panel_clients() -> None:
    for sid in _panel_sids_snapshot():
        try:
            socketio.server.disconnect(sid)
        except Exception:
            pass
    with _panel_sids_lock:
        _panel_sids.clear()


def _emit_panel_session_status() -> None:
    """원격 브라우저·패널에 앱 연결 상태 브로드캐스트."""
    panel_online = _has_panel_client()
    socketio.emit(
        "session_status",
        {
            "panel_online": panel_online,
            "broadcast_allowed": panel_online,
        },
    )


def _stop_broadcast_playback() -> None:
    if broadcast_command_queue:
        broadcast_command_queue.put({"action": "close_broadcast"})
    broadcast_state.stop()
    _emit_now_playing()
    _emit_playback_status()


def _has_panel_client() -> bool:
    with _panel_sids_lock:
        return len(_panel_sids) > 0


def _broadcast_playback_allowed() -> bool:
    return current_user.is_authenticated and _has_panel_client()


def _check_login_lock() -> tuple[bool, int]:
    """잠금 여부, 남은 초."""
    ip = _client_ip()
    rec = login_attempts.get(ip, {"count": 0, "lock_until": None})
    lock_until = rec.get("lock_until")
    if lock_until and datetime.utcnow() < lock_until:
        return True, int((lock_until - datetime.utcnow()).total_seconds()) + 1
    return False, 0


def _record_login_failure() -> None:
    ip = _client_ip()
    rec = login_attempts.setdefault(ip, {"count": 0, "lock_until": None})
    rec["count"] = rec.get("count", 0) + 1
    if rec["count"] >= 5:
        rec["lock_until"] = datetime.utcnow() + timedelta(seconds=30)
        rec["count"] = 0


def _clear_login_failures() -> None:
    login_attempts.pop(_client_ip(), None)


def _persist_playlist() -> None:
    """플레이리스트를 디스크에 저장."""
    save_playlist(broadcast_state.get_playlist_dicts())


def _emit_playlist() -> None:
    socketio.emit("playlist_update", {"playlist": broadcast_state.get_playlist_dicts()})


def _emit_now_playing() -> None:
    item = broadcast_state.current_item()
    socketio.emit(
        "now_playing",
        {
            "index": broadcast_state.current_index,
            "title": item.title if item else "",
            "type": item.type if item else "",
        },
    )


def _emit_playback_status() -> None:
    socketio.emit(
        "playback_status",
        {"status": broadcast_state.playback_status},
    )
    socketio.emit(
        "playback_status",
        {"status": broadcast_state.playback_status},
        namespace="/broadcast",
    )


def _emit_broadcast_track() -> None:
    """방송 키오스크 화면에 현재 트랙 반영 (자동 넘김 포함, 패널 연결과 무관)."""
    snap = broadcast_state.snapshot()
    socketio.emit("load_track", snap, namespace="/broadcast")


def _notify_broadcast(title: str, event: str) -> None:
    socketio.emit(event, {"title": title}, namespace="/broadcast")


def _notify_now_playing(title: str) -> None:
    """수동 이전/다음 — 짧은 안내만 (다음 곡 10초 안내는 막지 않음)."""
    socketio.emit(
        "now_playing_toast",
        {"title": title, "brief": True},
        namespace="/broadcast",
    )


def _fetch_youtube_duration(video_id: str) -> float:
    if not video_id:
        return 0.0
    try:
        return float(fetch_youtube_video_meta(video_id).get("duration") or 0)
    except Exception:
        return 0.0


def auto_setup_admin() -> None:
    """앱 시작 시 admin/1234 계정이 없으면 자동 생성 (온보딩 스킵)."""
    cfg = load_config()
    if not is_setup_complete(cfg):
        pw_hash = bcrypt.hashpw(b"1234", bcrypt.gensalt(rounds=12))
        cfg["admin_username"] = "admin"
        cfg["password_hash"] = pw_hash.decode("utf-8")
        cfg["onboarding_complete"] = True
        save_config(cfg)


def init_app(cfg: dict[str, Any]) -> None:
    global config_data
    config_data = cfg
    ensure_dirs()
    app.config["SECRET_KEY"] = cfg["secret_key"]
    app.config["WTF_CSRF_ENABLED"] = True
    # LAN IP(192.168.x.x)로 접속 시 세션·CSRF 쿠키 허용
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = False
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "login_page"
    # 저장된 플레이리스트 복원
    saved = load_playlist()
    if saved:
        broadcast_state.set_playlist(saved)


def login_required_socket(fn: Callable) -> Callable:
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            disconnect()
            return False
        return fn(*args, **kwargs)

    return wrapper


# --- HTTP 라우트 ---


@app.route("/")
def index():
    cfg = load_config()
    if not is_setup_complete(cfg):
        return redirect(url_for("setup_page"))
    if not current_user.is_authenticated:
        return redirect(url_for("login_page"))
    return render_template_string(_read_panel_html())


@app.route("/setup")
def setup_page():
    cfg = load_config()
    if is_setup_complete(cfg):
        return redirect(url_for("login_page"))
    return render_template_string(_read_auth_html("setup"))


@app.route("/login")
def login_page():
    cfg = load_config()
    if not is_setup_complete(cfg):
        return redirect(url_for("setup_page"))
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    return render_template_string(_read_auth_html("login"))


@app.route("/broadcast/")
def broadcast_page():
    return render_template_string(_read_broadcast_html())


@app.route("/api/csrf-token")
def api_csrf():
    return jsonify({"csrf_token": generate_csrf()})


@csrf.exempt
@app.route("/api/panel/window/<action>", methods=["POST", "GET"])
def api_panel_window(action: str):
    """네이티브 패널 창 제어 (localhost 전용, WebView2 API 대신 사용)."""
    if not _is_local_request():
        return jsonify({"error": "forbidden"}), 403
    action = (action or "").strip().lower()
    allowed = {"minimize", "maximize", "restore", "hide", "show"}
    if action not in allowed:
        return jsonify({"error": "bad_action"}), 400
    try:
        enqueue_panel_window_command(action)
        get_logger().info("HTTP panel window cmd: %s", action)
    except Exception:
        get_logger().error("enqueue panel cmd failed: %s", action, exc_info=True)
        return jsonify({"error": "queue_failed"}), 500
    return jsonify({"ok": True})


@app.route("/api/session/status")
def api_session_status():
    """앱(로컬) / 브라우저(원격) 상태 표시용."""
    local = _is_local_request()
    logged_in = current_user.is_authenticated
    panel_online = _has_panel_client()
    return jsonify(
        {
            "authenticated": logged_in,
            "viewer_is_local": local,
            "panel_online": panel_online,
            "broadcast_allowed": logged_in and panel_online,
            "status_label": (
                "서버 켜짐"
                if local
                else ("앱과 연결됨" if panel_online and logged_in else "앱 로그인 대기")
            ),
        }
    )


@app.route("/api/config/public")
def api_public_config():
    cfg = load_config()
    port = int(cfg.get("port", 8765))
    urls = panel_urls(port)
    return jsonify(
        {
            "port": port,
            "end_broadcast_image": cfg.get("end_broadcast_image", ""),
            "autostart": cfg.get("autostart", False),
            "setup_complete": is_setup_complete(cfg),
            "panel_local": urls["local"],
            "panel_lan": urls["lan"],
            "panel_primary_lan": urls["primary_lan"],
            "broadcast_browser": cfg.get("broadcast_browser", "auto"),
            "onboarding_complete": bool(cfg.get("onboarding_complete")),
        }
    )


@app.route("/api/network")
def api_network():
    """다른 기기(스마트폰 등)에서 접속할 LAN 주소."""
    if not current_user.is_authenticated:
        return jsonify({"error": "unauthorized"}), 401
    cfg = load_config()
    port = int(cfg.get("port", 8765))
    return jsonify(panel_urls(port))


@app.route("/api/displays")
def api_displays():
    if not current_user.is_authenticated:
        return jsonify({"error": "unauthorized"}), 401
    try:
        from screeninfo import get_monitors

        monitors = get_monitors()
        return jsonify(
            {
                "displays": [
                    {
                        "index": i,
                        "name": f"모니터 {i + 1} ({m.width}x{m.height})",
                        "x": m.x,
                        "y": m.y,
                        "width": m.width,
                        "height": m.height,
                    }
                    for i, m in enumerate(monitors)
                ]
            }
        )
    except Exception as exc:
        return jsonify({"error": str(exc), "displays": [{"index": 0, "name": "기본 모니터", "x": 0, "y": 0, "width": 1920, "height": 1080}]})


@app.route("/api/setup", methods=["POST"])
@csrf.exempt
def api_setup():
    cfg = load_config()
    if is_setup_complete(cfg):
        return jsonify(
            {"error": "이미 설정되었습니다.", "redirect": "/login", "already_setup": True}
        ), 400
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if len(username) < 2 or len(password) < 4:
        return jsonify({"error": "아이디(2자+)·비밀번호(4자+) 필요"}), 400

    pw_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12))
    cfg["admin_username"] = username
    cfg["password_hash"] = pw_hash.decode("utf-8")

    try:
        save_config(cfg)
        global config_data
        config_data = cfg
        app.config["SECRET_KEY"] = cfg["secret_key"]
        login_user(AdminUser(username), remember=True)
    except Exception as exc:
        rollback = load_config()
        rollback["admin_username"] = ""
        rollback["password_hash"] = ""
        save_config(rollback)
        config_data = rollback
        return jsonify({"error": f"설정 저장 실패: {exc}"}), 500

    resp = jsonify({"ok": True, "redirect": "/"})
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/api/login", methods=["POST"])
@csrf.exempt
def api_login():
    locked, remain = _check_login_lock()
    if locked:
        return jsonify({"error": f"30초 후 다시 시도 ({remain}초)"}), 429
    cfg = load_config()
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").encode("utf-8")
    stored = cfg.get("password_hash", "").encode("utf-8")
    if username != cfg.get("admin_username") or not bcrypt.checkpw(password, stored):
        _record_login_failure()
        return jsonify({"error": "아이디 또는 비밀번호가 올바르지 않습니다"}), 401
    _clear_login_failures()
    login_user(AdminUser(username), remember=True)
    _emit_panel_session_status()
    return jsonify({"ok": True})


@app.route("/api/logout", methods=["POST"])
def api_logout():
    logout_user()
    return jsonify({"ok": True})


@app.route("/api/password", methods=["POST"])
def api_change_password():
    if not current_user.is_authenticated:
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    current_pw = (data.get("current_password") or "").encode("utf-8")
    new_pw = data.get("new_password") or ""
    cfg = load_config()
    if not bcrypt.checkpw(current_pw, cfg["password_hash"].encode("utf-8")):
        return jsonify({"error": "현재 비밀번호가 올바르지 않습니다"}), 400
    if len(new_pw) < 4:
        return jsonify({"error": "새 비밀번호는 4자 이상"}), 400
    cfg["password_hash"] = bcrypt.hashpw(
        new_pw.encode("utf-8"), bcrypt.gensalt(rounds=12)
    ).decode("utf-8")
    save_config(cfg)
    return jsonify({"ok": True})


@app.route("/api/settings/reset-account", methods=["POST"])
def api_reset_account():
    """DB 계정 초기화 — 로컬 계정을 admin/1234로 리셋하고 재로그인."""
    cfg = load_config()
    pw_hash = bcrypt.hashpw(b"1234", bcrypt.gensalt(rounds=12))
    cfg["admin_username"] = "admin"
    cfg["password_hash"] = pw_hash.decode("utf-8")
    cfg["onboarding_complete"] = True
    save_config(cfg)
    global config_data
    config_data = cfg
    _disconnect_panel_clients()
    logout_user()
    _emit_panel_session_status()
    return jsonify({"ok": True, "redirect": "/login"})


@app.route("/api/youtube/from-url", methods=["POST"])
def api_youtube_from_url():
    """YouTube URL/ID → 메타데이터 (플레이리스트 추가용)."""
    if not current_user.is_authenticated:
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    raw = (data.get("url") or data.get("id") or "").strip()
    if not raw:
        return jsonify({"error": "YouTube 링크를 입력해 주세요"}), 400
    video_id = parse_youtube_video_id(raw)
    if not video_id:
        return jsonify({"error": "YouTube 링크를 인식할 수 없습니다"}), 400
    try:
        meta = fetch_youtube_video_meta(video_id)
    except Exception as exc:
        get_logger().warning("youtube meta failed id=%s: %s", video_id, exc)
        return jsonify({"error": f"영상 정보를 가져올 수 없습니다: {exc}"}), 502
    return jsonify(meta)


@app.route("/api/search", methods=["POST"])
def api_search():
    if not current_user.is_authenticated:
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    query = (data.get("query") or "").strip()
    if not query:
        return jsonify({"error": "검색어 필요"}), 400
    sid = request.sid if hasattr(request, "sid") else None

    def progress(pct: int, status: str) -> None:
        socketio.emit("search_progress", {"progress": pct, "status": status})

    try:
        results = search_youtube(query, max_results=10, progress_callback=progress)
        return jsonify({"results": results})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


def _local_upload_paths(original: str) -> tuple[Path, str]:
    """저장 파일명(ASCII 안전)과 플레이리스트 표시용 제목(한글 유지)."""
    raw = (original or "").replace("\\", "/").split("/")[-1].strip()
    if not raw:
        raise ValueError("파일명 없음")
    ext = Path(raw).suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXT:
        raise ValueError(f"허용되지 않는 확장자: {ext}")
    display_title = Path(raw).name
    token = secrets.token_hex(6)
    stem = secure_filename(Path(raw).stem) or "file"
    disk_name = f"{stem}_{token}{ext}"
    dest = UPLOADS_DIR / disk_name
    counter = 1
    while dest.exists():
        disk_name = f"{stem}_{token}_{counter}{ext}"
        dest = UPLOADS_DIR / disk_name
        counter += 1
    return dest, display_title


@app.route("/api/upload/local", methods=["POST"])
def api_upload_local():
    if not current_user.is_authenticated:
        return jsonify({"error": "unauthorized"}), 401
    if "file" not in request.files:
        return jsonify({"error": "파일 없음"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "파일명 없음"}), 400
    try:
        dest, display_title = _local_upload_paths(f.filename)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    f.save(dest)
    rel = f"uploads/{dest.name}"
    return jsonify(
        {
            "type": "local",
            "id": dest.name,
            "title": display_title,
            "path": rel,
        }
    )


@app.route("/api/settings/end-image", methods=["POST"])
def api_end_image():
    if not current_user.is_authenticated:
        return jsonify({"error": "unauthorized"}), 401
    if "file" not in request.files:
        return jsonify({"error": "파일 없음"}), 400
    f = request.files["file"]
    ext = Path(f.filename or "").suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        return jsonify({"error": "이미지 파일만 가능"}), 400
    safe = secure_filename(f.filename) or "end_image.png"
    dest = ASSETS_DIR / safe
    f.save(dest)
    cfg = load_config()
    cfg["end_broadcast_image"] = f"assets/{dest.name}"
    save_config(cfg)
    return jsonify({"ok": True, "path": cfg["end_broadcast_image"]})


@app.route("/api/settings/end-image", methods=["DELETE"])
def api_end_image_clear():
    if not current_user.is_authenticated:
        return jsonify({"error": "unauthorized"}), 401
    cfg = load_config()
    cfg["end_broadcast_image"] = ""
    save_config(cfg)
    return jsonify({"ok": True})


@app.route("/api/settings/broadcast-browser", methods=["GET", "POST"])
def api_broadcast_browser():
    if not current_user.is_authenticated:
        return jsonify({"error": "unauthorized"}), 401
    from broadcast_window import list_available_browsers

    if request.method == "GET":
        cfg = load_config()
        return jsonify(
            {
                "broadcast_browser": cfg.get("broadcast_browser", "auto"),
                "available": list_available_browsers(),
            }
        )
    data = request.get_json(silent=True) or {}
    choice = (data.get("broadcast_browser") or "auto").lower().strip()
    if choice not in ("auto", "edge", "chrome"):
        return jsonify({"error": "auto, edge, chrome 중 선택"}), 400
    cfg = load_config()
    cfg["broadcast_browser"] = choice
    save_config(cfg)
    return jsonify(
        {
            "ok": True,
            "broadcast_browser": choice,
            "available": list_available_browsers(),
        }
    )


@app.route("/api/settings/onboarding", methods=["GET", "POST"])
def api_onboarding():
    if not current_user.is_authenticated:
        return jsonify({"error": "unauthorized"}), 401
    cfg = load_config()
    if request.method == "GET":
        return jsonify({"complete": bool(cfg.get("onboarding_complete"))})
    data = request.get_json(silent=True) or {}
    if not data.get("agree_terms"):
        return jsonify({"error": "약관에 동의해 주세요"}), 400
    cfg["onboarding_complete"] = True
    save_config(cfg)
    return jsonify({"ok": True, "complete": True})


@app.route("/api/settings/autostart", methods=["POST"])
def api_autostart():
    if not current_user.is_authenticated:
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get("enabled"))
    cfg = load_config()
    cfg["autostart"] = enabled
    save_config(cfg)
    try:
        from startup import set_autostart

        set_autostart(enabled)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify({"ok": True, "enabled": enabled})


@app.route("/uploads/<path:filename>")
def uploads_file(filename):
    from flask import send_from_directory

    safe = secure_filename(Path(filename).name)
    return send_from_directory(UPLOADS_DIR, safe)


@app.route("/assets/<path:filename>")
def assets_file(filename):
    from flask import send_from_directory

    safe = secure_filename(Path(filename).name)
    return send_from_directory(ASSETS_DIR, safe)


# --- Cloudflare Sync (browser-direct approach) ---

@csrf.exempt
@app.route("/api/local/state")
def local_state():
    """브라우저 JS가 로컬 플레이리스트·설정을 Worker로 푸시하기 위해 읽는 엔드포인트."""
    cfg = load_config()
    playlist = broadcast_state.get_playlist_dicts()
    settings = {
        "end_broadcast_image": cfg.get("end_broadcast_image", ""),
        "autostart": str(cfg.get("autostart", False)).lower(),
        "broadcast_browser": cfg.get("broadcast_browser", "auto"),
        "port": str(cfg.get("port", 8765)),
    }
    return jsonify({"playlist": playlist, "settings": settings})


@csrf.exempt
@app.route("/api/local/apply", methods=["POST"])
def local_apply():
    """브라우저 JS가 Worker에서 당겨온 플레이리스트·설정을 앱에 적용."""
    data = request.get_json(force=True, silent=True) or {}
    pl = data.get("playlist") or []
    settings = data.get("settings") or {}

    # Apply playlist
    broadcast_state.set_playlist(pl)
    save_playlist(pl)

    # Apply settings
    cfg = load_config()
    changed = False
    for key in ("end_broadcast_image", "autostart", "broadcast_browser", "port"):
        if key in settings:
            val = settings[key]
            if key == "autostart":
                val = val in ("true", True)
            elif key == "port":
                val = int(val) if str(val).isdigit() else cfg.get("port", 8765)
            cfg[key] = val
            changed = True
    if changed:
        save_config(cfg)

    socketio.emit("state_update", broadcast_state.snapshot())
    return jsonify({"ok": True, "songs": len(pl)})


@csrf.exempt
@app.route("/api/cf/status")
def cf_status():
    cfg = load_config()
    return jsonify({
        "configured": True,   # Worker URL은 하드코딩 — 항상 True
        "worker_url": cloudflare_sync.WORKER_URL,
        "auto_pull_on_start": cfg.get("cf_auto_pull_on_start", True),
    })


@csrf.exempt
@app.route("/api/cf/config", methods=["GET", "POST"])
def cf_config():
    """자동 동기화 토글만 저장 (Worker URL/계정은 하드코딩)."""
    cfg = load_config()
    if request.method == "GET":
        return jsonify({
            "cf_auto_pull_on_start": cfg.get("cf_auto_pull_on_start", True),
        })
    body = request.get_json(force=True, silent=True) or {}
    if "cf_auto_pull_on_start" in body:
        cfg["cf_auto_pull_on_start"] = bool(body["cf_auto_pull_on_start"])
    save_config(cfg)
    return jsonify({"ok": True})


@csrf.exempt
@app.route("/api/cf/push", methods=["POST"])
def cf_push():
    """앱 동기화: push local playlist + settings → Cloudflare D1."""
    cfg = load_config()
    if not cloudflare_sync.is_configured(cfg):
        return jsonify({"error": "Cloudflare Worker URL이 설정되지 않았습니다"}), 400
    playlist = broadcast_state.get_playlist_dicts()
    settings = {
        "end_broadcast_image": cfg.get("end_broadcast_image", ""),
        "autostart": str(cfg.get("autostart", False)).lower(),
        "broadcast_browser": cfg.get("broadcast_browser", "auto"),
        "port": str(cfg.get("port", 8765)),
    }
    ok = cloudflare_sync.push(cfg, playlist, settings)
    if ok:
        return jsonify({"ok": True, "songs": len(playlist)})
    return jsonify({"error": "동기화 실패 — Worker URL 및 인증 정보를 확인해주세요"}), 502


@csrf.exempt
@app.route("/api/cf/pull", methods=["POST"])
def cf_pull():
    """데이터베이스 동기화: pull playlist + settings from Cloudflare D1 → app."""
    cfg = load_config()
    if not cloudflare_sync.is_configured(cfg):
        return jsonify({"error": "Cloudflare Worker URL이 설정되지 않았습니다"}), 400
    pl, settings = cloudflare_sync.pull(cfg)
    if pl is None:
        return jsonify({"error": "DB에서 데이터를 가져오지 못했습니다"}), 502

    # Apply playlist
    broadcast_state.set_playlist(pl)
    save_playlist(pl)

    # Apply settings
    if settings:
        changed = False
        for key in ("end_broadcast_image", "autostart", "broadcast_browser", "port"):
            if key in settings:
                val = settings[key]
                if key == "autostart":
                    val = val == "true" or val is True
                if key == "port":
                    val = int(val) if str(val).isdigit() else cfg.get("port", 8765)
                cfg[key] = val
                changed = True
        if changed:
            save_config(cfg)

    # Broadcast updated state to all connected panel clients
    socketio.emit("state_update", broadcast_state.snapshot())

    return jsonify({
        "ok": True,
        "songs": len(pl),
        "settings_applied": bool(settings),
    })


# --- SocketIO ---


@socketio.on("connect")
def on_panel_connect():
    """컨트롤 패널: 로그인 세션 필수 (localhost 포함)."""
    if not current_user.is_authenticated:
        return False
    _register_panel_client()
    emit(
        "session_status",
        {
            "authenticated": True,
            "panel_online": True,
            "broadcast_allowed": True,
            "viewer_is_local": _is_local_request(),
        },
    )


@socketio.on("disconnect")
def on_panel_disconnect():
    _unregister_panel_client()
    _emit_panel_session_status()


@socketio.on("connect", namespace="/broadcast")
def on_broadcast_connect():
    emit("state_sync", broadcast_state.snapshot())
    cfg = load_config()
    emit("config", {"end_broadcast_image": cfg.get("end_broadcast_image", "")})


def _require_auth_event(fn: Callable) -> Callable:
    @wraps(fn)
    def wrapper(data=None):
        if not current_user.is_authenticated:
            emit("control_denied", {"message": "로그인이 필요합니다."})
            return False
        return fn(data if data is not None else {})

    return wrapper


def _deny_broadcast_control(message: str) -> bool:
    emit("control_denied", {"message": message})
    return False


@socketio.on("add_song")
@_require_auth_event
def on_add_song(data):
    try:
        duration = float(data.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0
    vid = data.get("id", "") or ""
    if data.get("type", "youtube") == "youtube" and duration <= 0 and vid:
        duration = _fetch_youtube_duration(vid)
    item = {
        "type": data.get("type", "youtube"),
        "id": vid,
        "title": data.get("title", "제목 없음"),
        "thumbnail": data.get("thumbnail", ""),
        "path": data.get("path", ""),
        "duration": max(0, duration),
    }
    idx = broadcast_state.add_song(item)
    _persist_playlist()
    _emit_playlist()
    cur = broadcast_state.current_index
    if cur >= 0 and idx > cur:
        _notify_broadcast(item["title"], "song_added_notify")
    return {"ok": True}


@socketio.on("reorder")
@_require_auth_event
def on_reorder(data):
    broadcast_state.reorder(int(data.get("from_idx", 0)), int(data.get("to_idx", 0)))
    _persist_playlist()
    _emit_playlist()
    _emit_now_playing()


@socketio.on("remove_song")
@_require_auth_event
def on_remove_song(data):
    broadcast_state.remove_at(int(data.get("index", -1)))
    _persist_playlist()
    _emit_playlist()
    _emit_now_playing()


@socketio.on("control")
@_require_auth_event
def on_control(data):
    action = data.get("action")
    display_index = int(data.get("display_index", 0))
    playback_actions = {"start", "play", "pause", "next", "prev", "stop"}

    if action in playback_actions and not _broadcast_playback_allowed():
        if not _has_panel_client():
            return _deny_broadcast_control(
                "앱에 로그인되어 있지 않습니다. 방송 PC 앱에서 로그인해 주세요."
            )
        return _deny_broadcast_control("앱에 로그인되어 있어야 방송을 제어할 수 있습니다.")

    if action == "start":
        item = broadcast_state.start_playback()
        if item and broadcast_command_queue:
            broadcast_command_queue.put(
                {"action": "open_broadcast", "display_index": display_index}
            )
        _emit_now_playing()
        _emit_playback_status()
        _emit_playlist()
        _emit_broadcast_track()
    elif action == "play":
        if broadcast_state.current_index < 0:
            broadcast_state.start_playback()
        else:
            broadcast_state.resume()
        _emit_playback_status()
        _emit_broadcast_track()
    elif action == "pause":
        broadcast_state.pause()
        _emit_playback_status()
    elif action == "next":
        item = broadcast_state.advance_next()
        _emit_now_playing()
        _emit_playback_status()
        if item:
            _emit_broadcast_track()
            _notify_now_playing(item.title)
        else:
            socketio.emit("broadcast_ended", {}, namespace="/broadcast")
    elif action == "prev":
        item = broadcast_state.advance_previous()
        _emit_now_playing()
        _emit_playback_status()
        if item:
            _emit_broadcast_track()
            _notify_now_playing(item.title)
    elif action == "stop":
        broadcast_state.stop()
        _emit_now_playing()
        _emit_playback_status()
        socketio.emit("broadcast_ended", {}, namespace="/broadcast")


@socketio.on("request_stop", namespace="/broadcast")
def on_request_stop(_data=None):
    """방송 화면 ESC — 종료 화면 표시 (창은 ESC로 닫기)."""
    broadcast_state.stop()
    _emit_now_playing()
    _emit_playback_status()
    socketio.emit("broadcast_ended", {}, namespace="/broadcast")


@socketio.on("song_finished", namespace="/broadcast")
def on_song_finished(data=None):
    """방송 화면에서 곡 종료 시 — 다음 곡 또는 방송 종료 화면."""
    payload = data if isinstance(data, dict) else {}
    finished_idx = payload.get("index")
    if finished_idx is not None:
        try:
            finished_idx = int(finished_idx)
        except (TypeError, ValueError):
            finished_idx = None
    if finished_idx is not None and broadcast_state.current_index > finished_idx:
        _emit_broadcast_track()
        return
    item = broadcast_state.advance_next()
    _emit_now_playing()
    _emit_playback_status()
    _emit_playlist()
    if item:
        _emit_broadcast_track()
        _notify_now_playing(item.title)
    else:
        broadcast_state.stop()
        _emit_now_playing()
        _emit_playback_status()
        socketio.emit("broadcast_ended", {}, namespace="/broadcast")


@socketio.on("request_sync", namespace="/broadcast")
def on_broadcast_request_sync(_data=None):
    """방송 화면 — 다음 곡 로드 실패 시 상태 재동기화."""
    snap = broadcast_state.snapshot()
    socketio.emit("load_track", snap, namespace="/broadcast")
    if broadcast_state.current_index < 0:
        socketio.emit("broadcast_ended", {}, namespace="/broadcast")


@socketio.on("playback_progress", namespace="/broadcast")
def on_playback_progress_from_broadcast(data):
    """방송 키오스크 창(비로그인) → 패널 진행률 바."""
    socketio.emit("playback_progress", data)


@socketio.on("playback_progress")
def on_playback_progress(data):
    socketio.emit("playback_progress", data)


@socketio.on("get_state")
@_require_auth_event
def on_get_state(_data):
    emit("state_sync", broadcast_state.snapshot())
    _emit_playlist()
    _emit_now_playing()
    _emit_playback_status()


def _read_panel_html() -> str:
    return (BUNDLE_DIR / "panel" / "index.html").read_text(encoding="utf-8")


def _read_auth_html(mode: str) -> str:
    html = (BUNDLE_DIR / "panel" / "auth.html").read_text(encoding="utf-8")
    return html.replace("{{MODE}}", mode)


def _read_broadcast_html() -> str:
    return (BUNDLE_DIR / "broadcast" / "index.html").read_text(encoding="utf-8")


def create_socketio_app(cfg: dict[str, Any]) -> tuple[Flask, SocketIO]:
    init_app(cfg)
    return app, socketio


def run_server(port: int) -> None:
    socketio.run(
        app,
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
        allow_unsafe_werkzeug=True,
    )


def start_server_thread(port: int) -> threading.Thread:
    t = threading.Thread(target=run_server, args=(port,), daemon=True)
    t.start()
    return t
