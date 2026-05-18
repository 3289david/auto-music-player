"""
빌드용 — WebView2 고정 런타임을 NuGet에서 받아 WebView2Runtime/ 에 둡니다.
패키지: WebView2.Runtime.X64 (NuGet)
"""
from __future__ import annotations

import io
import json
import shutil
import sys
import zipfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "WebView2Runtime"
# NuGet v3 flat container ID (소문자)
NUGET_ID = "webview2.runtime.x64"
# 404 나던 잘못된 ID 대신 실제 패키지 버전
PINNED_VERSION = "131.0.2903.112"
FALLBACK_VERSIONS = (
    "148.0.3967.70",
    "131.0.2903.112",
    "130.0.2849.80",
    "129.0.2792.89",
)
_MARKER_NAMES = ("msedgewebview2.exe", "msedge.exe")


def _fetch_json(url: str) -> dict:
    req = Request(url, headers={"User-Agent": "schoolair-build/1.0"})
    with urlopen(req, timeout=120) as resp:
        return json.load(resp)


def _download_bytes(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": "schoolair-build/1.0"})
    with urlopen(req, timeout=900) as resp:
        return resp.read()


def _list_versions() -> list[str]:
    try:
        data = _fetch_json(f"https://api.nuget.org/v3-flatcontainer/{NUGET_ID}/index.json")
        return list(data.get("versions") or [])
    except (HTTPError, URLError, OSError, json.JSONDecodeError):
        return []


def _pick_version() -> str:
    versions = _list_versions()
    if versions:
        return versions[-1]
    for v in FALLBACK_VERSIONS:
        url = (
            f"https://api.nuget.org/v3-flatcontainer/{NUGET_ID}/{v}/"
            f"{NUGET_ID}.{v}.nupkg"
        )
        try:
            req = Request(url, method="HEAD", headers={"User-Agent": "schoolair-build/1.0"})
            with urlopen(req, timeout=30) as resp:
                if resp.status < 400:
                    return v
        except Exception:
            continue
    return PINNED_VERSION


def _nupkg_url(version: str) -> str:
    return (
        f"https://api.nuget.org/v3-flatcontainer/{NUGET_ID}/{version}/"
        f"{NUGET_ID}.{version}.nupkg"
    )


def _find_runtime_dir(extract_root: Path) -> Path | None:
    for name in _MARKER_NAMES:
        hits = list(extract_root.rglob(name))
        if hits:
            return hits[0].parent
    return None


def main() -> int:
    version = _pick_version()
    url = _nupkg_url(version)
    print(f"WebView2 Runtime (X64) {version} 다운로드 중…")
    print(url)

    try:
        data = _download_bytes(url)
    except HTTPError as exc:
        print(f"[오류] 다운로드 실패 HTTP {exc.code}", file=sys.stderr)
        print(
            "NuGet 패키지 WebView2.Runtime.X64 가 없거나 버전이 다릅니다.\n"
            "https://www.nuget.org/packages/WebView2.Runtime.X64 에서 버전을 확인하세요.",
            file=sys.stderr,
        )
        return 1
    except URLError as exc:
        print(f"[오류] 네트워크: {exc.reason}", file=sys.stderr)
        return 1

    tmp = ROOT / "_wv2_unpack"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir()

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        zf.extractall(tmp)

    src_dir = _find_runtime_dir(tmp)
    if not src_dir:
        print("[오류] nupkg 안에 msedgewebview2.exe / msedge.exe 를 찾지 못했습니다.", file=sys.stderr)
        shutil.rmtree(tmp, ignore_errors=True)
        return 1

    if TARGET.exists():
        shutil.rmtree(TARGET)
    shutil.copytree(src_dir, TARGET)
    shutil.rmtree(tmp, ignore_errors=True)

    marker = None
    for name in _MARKER_NAMES:
        if (TARGET / name).is_file():
            marker = TARGET / name
            break

    print(f"완료: {TARGET}")
    print(f"  → {marker or TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
