"""YouTube URL 파싱·메타데이터 (yt-dlp)."""
from __future__ import annotations

import re
from typing import Any

import yt_dlp

_YT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{11}$")
_YT_URL_PATTERNS = (
    re.compile(r"(?:youtube\.com/watch\?(?:[^&]+&)*v=|youtube\.com/watch\?v=)([a-zA-Z0-9_-]{11})"),
    re.compile(r"youtu\.be/([a-zA-Z0-9_-]{11})"),
    re.compile(r"youtube\.com/embed/([a-zA-Z0-9_-]{11})"),
    re.compile(r"youtube\.com/shorts/([a-zA-Z0-9_-]{11})"),
    re.compile(r"youtube\.com/live/([a-zA-Z0-9_-]{11})"),
)

_YT_EXTRACTOR_ARGS = {
    "youtube": {
        "player_client": ["android", "web", "ios"],
    }
}

_YT_FORMAT_CANDIDATES = (
    "best[acodec!=none][vcodec!=none]/"
    "bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
    "bestvideo+bestaudio/"
    "best"
)


def parse_youtube_video_id(value: str) -> str | None:
    """URL 또는 11자리 영상 ID → video id."""
    s = (value or "").strip()
    if not s:
        return None
    if _YT_ID_RE.fullmatch(s):
        return s
    for pat in _YT_URL_PATTERNS:
        m = pat.search(s)
        if m:
            return m.group(1)
    return None


def _base_ydl_opts() -> dict[str, Any]:
    return {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extractor_args": _YT_EXTRACTOR_ARGS,
    }


def fetch_youtube_video_meta(video_id: str) -> dict[str, Any]:
    """제목·썸네일·길이(초) 조회."""
    if not video_id:
        raise ValueError("video_id 필요")
    ydl_opts = _base_ydl_opts()
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(
            f"https://www.youtube.com/watch?v={video_id}", download=False
        )
    info = info or {}
    vid = info.get("id") or video_id
    thumb = info.get("thumbnail") or ""
    if not thumb:
        thumb = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
    try:
        duration = float(info.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    return {
        "type": "youtube",
        "id": vid,
        "title": info.get("title") or "제목 없음",
        "thumbnail": thumb,
        "duration": max(0.0, duration),
    }


def _format_score(fmt: dict[str, Any]) -> tuple[int, int, int]:
    """높을수록 선호: 영상+음성 > 영상만 > 음성만, 해상도·비트레이트."""
    has_video = fmt.get("vcodec") not in (None, "none")
    has_audio = fmt.get("acodec") not in (None, "none")
    try:
        height = int(fmt.get("height") or 0)
    except (TypeError, ValueError):
        height = 0
    try:
        tbr = int(fmt.get("tbr") or 0)
    except (TypeError, ValueError):
        tbr = 0
    if has_video and has_audio:
        kind = 2
    elif has_video:
        kind = 1
    elif has_audio:
        kind = 0
    else:
        kind = -1
    return (kind, height, tbr)


def _pick_stream_url(info: dict[str, Any]) -> str:
    url = info.get("url")
    if url:
        return str(url)

    formats = [f for f in (info.get("formats") or []) if f.get("url")]
    combined = [
        f
        for f in formats
        if f.get("vcodec") not in (None, "none")
        and f.get("acodec") not in (None, "none")
    ]
    if combined:
        combined.sort(key=_format_score)
        return str(combined[-1]["url"])

    requested = info.get("requested_formats") or []
    if requested:
        parts = [f for f in requested if f.get("url")]
        if len(parts) == 1:
            return str(parts[0]["url"])
        video_parts = [
            f for f in parts if f.get("vcodec") not in (None, "none")
        ]
        if video_parts:
            video_parts.sort(key=_format_score)
            return str(video_parts[-1]["url"])

    if formats:
        formats.sort(key=_format_score)
        return str(formats[-1]["url"])

    raise ValueError("재생 가능한 스트림 URL을 찾을 수 없습니다")


def _extract_stream_info(video_id: str, format_selector: str) -> dict[str, Any]:
    ydl_opts = {
        **_base_ydl_opts(),
        "format": format_selector,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(
            f"https://www.youtube.com/watch?v={video_id}", download=False
        )
    info = info or {}
    url = _pick_stream_url(info)
    try:
        duration = float(info.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    http_headers: dict[str, str] = {}
    raw_headers = info.get("http_headers")
    if isinstance(raw_headers, dict):
        http_headers = {str(k): str(v) for k, v in raw_headers.items()}
    return {
        "url": url,
        "duration": max(0.0, duration),
        "http_headers": http_headers,
    }


def fetch_youtube_stream_info(video_id: str) -> dict[str, Any]:
    """임베드 불가 영상 — yt-dlp 직접 스트림 (방송 화면 <video> 재생용)."""
    if not video_id:
        raise ValueError("video_id 필요")
    last_error: Exception | None = None
    for fmt in _YT_FORMAT_CANDIDATES:
        try:
            return _extract_stream_info(video_id, fmt)
        except Exception as exc:
            last_error = exc
            continue
    if last_error:
        raise last_error
    raise ValueError("스트림을 가져오지 못했습니다")
