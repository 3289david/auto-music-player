"""YouTube 검색 (yt-dlp, 다운로드 없음)."""
from __future__ import annotations

from typing import Any, Callable

import yt_dlp


def search_youtube(
    query: str,
    max_results: int = 10,
    progress_callback: Callable[[int, str], None] | None = None,
) -> list[dict[str, Any]]:
    """검색어로 YouTube 영상 메타데이터 목록 반환."""
    if progress_callback:
        progress_callback(10, "검색 준비 중...")

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
    }

    if progress_callback:
        progress_callback(40, "YouTube 검색 중...")

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(
                f"ytsearch{max_results}:{query}", download=False
            )
    except Exception as exc:
        if progress_callback:
            progress_callback(100, f"검색 실패: {exc}")
        raise

    if progress_callback:
        progress_callback(90, "결과 정리 중...")

    entries = (result or {}).get("entries") or []
    items: list[dict[str, Any]] = []
    for entry in entries:
        if not entry:
            continue
        vid = entry.get("id") or ""
        thumb = entry.get("thumbnail") or ""
        if not thumb and vid:
            thumb = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
        items.append(
            {
                "id": vid,
                "title": entry.get("title") or "제목 없음",
                "thumbnail": thumb,
                "duration": entry.get("duration") or 0,
            }
        )

    if progress_callback:
        progress_callback(100, "완료")

    return items
