"""방송 상태 및 플레이리스트 관리 (서버·방송 화면 공유)."""
from __future__ import annotations

import copy
import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PlaylistItem:
    type: str  # 'youtube' | 'local'
    id: str
    title: str
    thumbnail: str = ""
    path: str = ""  # 로컬 파일 상대 경로 (uploads/...)
    duration: float = 0  # 초 (YouTube 검색 메타·종료 타이머용)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "id": self.id,
            "title": self.title,
            "thumbnail": self.thumbnail,
            "path": self.path,
            "duration": self.duration,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlaylistItem":
        try:
            duration = float(data.get("duration") or 0)
        except (TypeError, ValueError):
            duration = 0
        return cls(
            type=data.get("type", "youtube"),
            id=data.get("id", ""),
            title=data.get("title", "제목 없음"),
            thumbnail=data.get("thumbnail", ""),
            path=data.get("path", ""),
            duration=max(0, duration),
        )


@dataclass
class BroadcastState:
    playlist: list[PlaylistItem] = field(default_factory=list)
    current_index: int = -1
    playback_status: str = "stopped"  # playing | paused | stopped | ended
    broadcast_active: bool = False
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "playlist": [p.to_dict() for p in self.playlist],
                "current_index": self.current_index,
                "playback_status": self.playback_status,
                "broadcast_active": self.broadcast_active,
            }

    def set_playlist(self, items: list[dict[str, Any]]) -> None:
        with self._lock:
            self.playlist = [PlaylistItem.from_dict(i) for i in items]

    def get_playlist_dicts(self) -> list[dict[str, Any]]:
        with self._lock:
            return [p.to_dict() for p in self.playlist]

    def add_song(self, item: dict[str, Any], insert_after_current: bool = True) -> int:
        """곡 추가. 삽입 위치 인덱스 반환."""
        with self._lock:
            new_item = PlaylistItem.from_dict(item)
            if not self.playlist:
                self.playlist.append(new_item)
                return 0
            if insert_after_current and self.current_index >= 0:
                idx = min(self.current_index + 1, len(self.playlist))
            else:
                idx = len(self.playlist)
            self.playlist.insert(idx, new_item)
            if self.current_index >= idx:
                self.current_index += 1
            return idx

    def remove_at(self, index: int) -> bool:
        with self._lock:
            if index < 0 or index >= len(self.playlist):
                return False
            self.playlist.pop(index)
            if self.current_index == index:
                self.current_index = min(index, len(self.playlist) - 1)
                if not self.playlist:
                    self.current_index = -1
                    self.playback_status = "stopped"
            elif self.current_index > index:
                self.current_index -= 1
            return True

    def reorder(self, from_idx: int, to_idx: int) -> bool:
        with self._lock:
            if (
                from_idx < 0
                or from_idx >= len(self.playlist)
                or to_idx < 0
                or to_idx >= len(self.playlist)
            ):
                return False
            item = self.playlist.pop(from_idx)
            self.playlist.insert(to_idx, item)
            cur = self.current_index
            if cur == from_idx:
                self.current_index = to_idx
            elif from_idx < cur <= to_idx:
                self.current_index -= 1
            elif to_idx <= cur < from_idx:
                self.current_index += 1
            return True

    def current_item(self) -> PlaylistItem | None:
        with self._lock:
            if self.current_index < 0 or self.current_index >= len(self.playlist):
                return None
            return copy.deepcopy(self.playlist[self.current_index])

    def next_item(self) -> PlaylistItem | None:
        with self._lock:
            nxt = self.current_index + 1
            if nxt < 0 or nxt >= len(self.playlist):
                return None
            return copy.deepcopy(self.playlist[nxt])

    def start_playback(self) -> PlaylistItem | None:
        with self._lock:
            if not self.playlist:
                self.current_index = -1
                self.playback_status = "stopped"
                return None
            if self.current_index < 0:
                self.current_index = 0
            self.playback_status = "playing"
            self.broadcast_active = True
            return copy.deepcopy(self.playlist[self.current_index])

    def advance_next(self) -> PlaylistItem | None:
        with self._lock:
            if not self.playlist:
                self.current_index = -1
                self.playback_status = "ended"
                self.broadcast_active = False
                return None
            nxt = self.current_index + 1
            if nxt >= len(self.playlist):
                self.current_index = -1
                self.playback_status = "ended"
                self.broadcast_active = False
                return None
            self.current_index = nxt
            self.playback_status = "playing"
            self.broadcast_active = True
            return copy.deepcopy(self.playlist[self.current_index])

    def advance_previous(self) -> PlaylistItem | None:
        """이전 곡으로 이동 (첫 곡이면 첫 곡 유지)."""
        with self._lock:
            if not self.playlist:
                self.current_index = -1
                self.playback_status = "stopped"
                return None
            if self.current_index <= 0:
                self.current_index = 0
            else:
                self.current_index -= 1
            self.playback_status = "playing"
            self.broadcast_active = True
            return copy.deepcopy(self.playlist[self.current_index])

    def pause(self) -> None:
        with self._lock:
            if self.playback_status == "playing":
                self.playback_status = "paused"

    def resume(self) -> None:
        with self._lock:
            if self.playback_status == "paused":
                self.playback_status = "playing"

    def stop(self) -> None:
        with self._lock:
            self.current_index = -1
            self.playback_status = "stopped"
            self.broadcast_active = False
