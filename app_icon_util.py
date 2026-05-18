"""앱 아이콘 경로·Windows 작업 표시줄 ID."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from config_store import BUNDLE_DIR, INSTALL_DIR

APP_USER_MODEL_ID = "SchoolAir.Eumbang2ndGen.Panel.v1"


def find_resource(name: str) -> Path | None:
    """번들(_MEIPASS) → exe 옆 폴더 순으로 리소스 탐색."""
    for base in (BUNDLE_DIR, INSTALL_DIR):
        path = base / name
        if path.is_file():
            return path.resolve()
    return None


def ensure_app_icon_ico() -> Path | None:
    """작업 표시줄·창용 .ico (exe 옆에 생성)."""
    target = (INSTALL_DIR / "app_icon.ico").resolve()
    if target.is_file():
        return target

    bundled_ico = find_resource("app_icon.ico")
    if bundled_ico and bundled_ico != target:
        try:
            shutil.copy2(bundled_ico, target)
            return target
        except OSError:
            return bundled_ico

    png = find_resource("14720088.png")
    if not png:
        return None
    try:
        from PIL import Image

        Image.open(png).convert("RGBA").save(
            target,
            format="ICO",
            sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)],
        )
        return target
    except Exception:
        return png


def apply_windows_app_identity() -> None:
    """exe·창이 같은 작업 표시줄 아이콘을 쓰도록 AppUserModelID 설정."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        pass


def load_tray_image():
    """pystray용 PIL 이미지."""
    from PIL import Image, ImageDraw

    path = find_resource("14720088.png")
    if path:
        return Image.open(path).convert("RGBA").resize((64, 64), Image.Resampling.LANCZOS)

    ico = ensure_app_icon_ico()
    if ico and ico.suffix.lower() == ".ico":
        return Image.open(ico).convert("RGBA").resize((64, 64), Image.Resampling.LANCZOS)

    img = Image.new("RGBA", (64, 64), (49, 130, 246, 255))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((8, 8, 56, 56), radius=12, fill=(255, 255, 255, 230))
    draw.text((18, 22), "2", fill=(49, 130, 246, 255))
    return img
