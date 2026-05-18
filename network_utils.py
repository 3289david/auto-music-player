"""LAN(사설망) IP 주소 조회."""
from __future__ import annotations

import socket


def get_lan_ips() -> list[str]:
    """같은 Wi-Fi에서 접속 가능한 IPv4 주소 목록."""
    found: list[str] = []

    # 활성 인터페이스(외부로 나가는 경로) IP
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                found.append(ip)
    except OSError:
        pass

    # 호스트명에 묶인 주소
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127.") and ip not in found:
                found.append(ip)
    except OSError:
        pass

    return found


def panel_urls(port: int) -> dict[str, list[str] | str]:
    """패널 접속 URL (로컬 + LAN)."""
    local = f"http://127.0.0.1:{port}/"
    lan = [f"http://{ip}:{port}/" for ip in get_lan_ips()]
    primary_lan = lan[0] if lan else ""
    return {
        "local": local,
        "lan": lan,
        "primary_lan": primary_lan,
    }
