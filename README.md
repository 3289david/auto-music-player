# 🎵 음방시스템 — School Broadcast Music Player

> **학교 방송용 음악 재생 시스템** — Windows 앱 + Cloudflare 클라우드 백엔드 + 관리자 웹 포털

[![Cloudflare Workers](https://img.shields.io/badge/Cloudflare-Workers-F38020?logo=cloudflare&logoColor=white)](https://workers.cloudflare.com/)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-3.0-000000?logo=flask)](https://flask.palletsprojects.com/)
[![D1 Database](https://img.shields.io/badge/D1-Database-F38020?logo=cloudflare)](https://developers.cloudflare.com/d1/)

---

## ✨ 주요 기능

| 기능 | 설명 |
|------|------|
| 🎬 **방송 재생** | YouTube 영상·로컬 파일을 학교 방송 화면에 자동 재생 |
| ☁️ **클라우드 동기화** | Cloudflare D1 DB와 실시간 양방향 동기화 |
| 🌐 **웹 관리 포털** | 브라우저에서 플레이리스트 관리 (로그인 필요) |
| 📱 **원격 제어** | 같은 Wi-Fi의 모든 기기에서 패널 접속 가능 |
| 🔄 **자동 동기화** | 앱 실행 시 DB에서 최신 플레이리스트 자동 로드 |
| 🔒 **인증 시스템** | JWT 기반 API 인증, bcrypt 비밀번호 해싱 |

---

## 🏗️ 아키텍처

```
┌─────────────────────────────────────────────────────┐
│                  Windows 앱 (Python)                 │
│  Flask + SocketIO + WebView2 패널                    │
│  ┌──────────┐  ┌─────────────┐  ┌────────────────┐  │
│  │ 플레이리  │  │  방송 화면  │  │ cloudflare_    │  │
│  │ 스트 관리 │  │ (YouTube)   │  │ sync.py        │  │
│  └──────────┘  └─────────────┘  └───────┬────────┘  │
└────────────────────────────────────────-┼───────────┘
                                          │ HTTPS
                    ┌─────────────────────▼──────────────┐
                    │   Cloudflare Worker (Hono)          │
                    │   /api/auth  /api/playlist          │
                    │   /api/settings  /api/sync          │
                    │         │                           │
                    │   ┌─────▼──────┐                   │
                    │   │  D1 Database│                   │
                    │   │  (SQLite)   │                   │
                    │   └────────────┘                   │
                    └────────────────────────────────────┘
                                          │
                    ┌─────────────────────▼──────────────┐
                    │   관리자 웹 포털 (Cloudflare Pages) │
                    │   login.html + index.html           │
                    │   플레이리스트 CRUD + 설정 관리     │
                    └────────────────────────────────────┘
```

---

## 🚀 빠른 시작

### 1. Cloudflare Worker 배포

```bash
cd backend

# 의존성 설치
npm install

# D1 데이터베이스 생성
npx wrangler d1 create auto-music-player-db

# wrangler.toml의 database_id를 위 명령 출력값으로 교체

# 스키마 적용 (로컬)
npm run db:init

# 스키마 적용 (원격)
npm run db:init:remote

# JWT 시크릿 설정
npx wrangler secret put JWT_SECRET

# Worker 배포
npm run deploy
```

배포 후 Worker URL을 메모해 두세요: `https://auto-music-player-backend.YOUR_SUBDOMAIN.workers.dev`

### 2. 관리자 웹 포털 설정

```bash
cd website

# env.js에서 API URL 수정
# window.__API_BASE__ = 'https://auto-music-player-backend.YOUR_SUBDOMAIN.workers.dev';
```

- Cloudflare Pages, GitHub Pages, Netlify 등 어디서든 호스팅 가능
- `website/` 폴더 전체를 정적 사이트로 배포

**기본 로그인 정보**
```
아이디: admin
비밀번호: 1234
```

### 3. Windows 앱 실행

```bash
# 의존성 설치
pip install -r requirements.txt

# 앱 실행
python main.py
```

앱이 실행되면:
1. 패널 WebView2 창이 열립니다
2. 설정 탭 → Cloudflare 연동 설정에서 Worker URL 입력
3. 앱 재시작 시 DB에서 플레이리스트 자동 로드

---

## ☁️ 동기화 버튼 안내

앱 사이드바의 **☁️ 클라우드 동기화** 섹션:

| 버튼 | 방향 | 설명 |
|------|------|------|
| 📤 **앱 동기화** | 앱 → DB | 현재 앱의 플레이리스트·설정을 Cloudflare DB에 저장 |
| 📥 **데이터베이스 동기화** | DB → 앱 | Cloudflare DB의 최신 데이터를 앱에 적용 |

> 앱 실행 시 DB에서 자동으로 데이터를 가져옵니다 (설정에서 끌 수 있음).

웹 포털에도 동일한 동기화 버튼이 있습니다.

---

## 📁 디렉토리 구조

```
auto_music_player/
│
├── 🐍 Windows 앱 (Python)
│   ├── main.py              # 진입점
│   ├── server.py            # Flask + SocketIO API
│   ├── cloudflare_sync.py   # ☁️ Cloudflare D1 동기화 모듈 (신규)
│   ├── config_store.py      # 설정 로드·저장
│   ├── playlist_store.py    # 플레이리스트 로드·저장
│   ├── state.py             # 방송 상태 관리
│   ├── broadcast_window.py  # 방송 화면 제어
│   ├── panel_window.py      # WebView2 패널
│   ├── panel/               # 컨트롤 패널 HTML/CSS/JS
│   │   ├── index.html       # 메인 패널 (동기화 버튼 포함)
│   │   └── static/          # CSS·JS 에셋
│   └── broadcast/           # 방송 화면 HTML
│
├── ☁️ backend/               # Cloudflare Worker
│   ├── src/index.js         # Worker API (Hono)
│   ├── schema.sql           # D1 스키마 + 초기 데이터
│   ├── wrangler.toml        # Worker 설정
│   ├── package.json
│   └── .dev.vars.example    # 환경 변수 예시
│
└── 🌐 website/               # 관리자 웹 포털
    ├── login.html           # 로그인 페이지
    ├── index.html           # 대시보드 (플레이리스트·설정 관리)
    ├── env.js               # API URL 설정
    ├── css/style.css        # 다크 테마 스타일
    ├── js/app.js            # SPA 로직
    └── .env.example
```

---

## 🔌 API 엔드포인트

모든 API는 `Authorization: Bearer <JWT>` 헤더가 필요합니다 (로그인 제외).

| Method | Path | 설명 |
|--------|------|------|
| `POST` | `/api/auth/login` | 로그인 → JWT 반환 |
| `GET` | `/api/auth/me` | 현재 사용자 확인 |
| `GET` | `/api/playlist` | 전체 플레이리스트 조회 |
| `POST` | `/api/playlist` | 곡 추가 |
| `PUT` | `/api/playlist/:id` | 곡 정보 수정 |
| `DELETE` | `/api/playlist/:id` | 곡 삭제 |
| `PUT` | `/api/playlist/reorder` | 순서 일괄 변경 |
| `DELETE` | `/api/playlist` | 전체 삭제 |
| `GET` | `/api/settings` | 설정 조회 |
| `PUT` | `/api/settings` | 설정 업데이트 |
| `POST` | `/api/sync/push` | 앱 → DB 전체 동기화 |
| `GET` | `/api/sync/pull` | DB → 앱 전체 동기화 |

---

## 🗄️ D1 데이터베이스 스키마

```sql
-- 사용자 (기본: admin / 1234)
CREATE TABLE users (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  username      TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  created_at    TEXT DEFAULT (datetime('now'))
);

-- 플레이리스트
CREATE TABLE playlist (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  sort_order INTEGER NOT NULL DEFAULT 0,
  type       TEXT NOT NULL DEFAULT 'youtube',
  song_id    TEXT NOT NULL,
  title      TEXT NOT NULL,
  thumbnail  TEXT DEFAULT '',
  path       TEXT DEFAULT '',
  duration   REAL DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);

-- 설정 (키-값)
CREATE TABLE settings (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_at TEXT DEFAULT (datetime('now'))
);
```

---

## ⚙️ 환경 변수

### backend/.dev.vars (로컬 개발)
```env
JWT_SECRET=your-super-secret-jwt-key-minimum-32-characters
```

### backend/wrangler.toml
```toml
database_id = "YOUR_D1_DATABASE_ID"  # wrangler d1 create로 생성
```

### website/env.js
```js
window.__API_BASE__ = 'https://auto-music-player-backend.YOUR_SUBDOMAIN.workers.dev';
```

---

## 🛠️ 개발 환경

**Windows 앱**
- Python 3.11+
- Flask 3.0, Flask-SocketIO, Flask-Login, Flask-WTF
- bcrypt, yt-dlp, WebView2, pystray

**Cloudflare Worker**
- Hono 4.x (경량 Web Framework)
- Wrangler 3.x
- D1 Database (SQLite 호환)
- Web Crypto API (JWT 서명)

**웹 포털**
- Vanilla HTML/CSS/JavaScript (빌드 불필요)
- Sortable.js (드래그 순서 변경)
- Noto Sans KR (한국어 폰트)

---

## 📦 Windows 앱 빌드

```bash
# 의존성 (빌드용)
pip install -r requirements-build.txt

# PyInstaller 빌드
build.bat
# 또는
python -m PyInstaller build.spec
```

빌드 결과물은 `dist/` 폴더에 생성됩니다.

---

## 🔐 보안

- 비밀번호: PBKDF2-SHA256 (100,000 iterations) 해싱
- 초기 admin/1234 계정은 최초 로그인 시 자동으로 안전한 해시로 마이그레이션
- JWT 토큰 만료: 7일
- CORS: `*` (내부 네트워크 전용 → 필요 시 Worker URL로 제한 권장)
- CSRF 보호: Flask-WTF (앱 패널)

---

## 📝 라이선스

원본 코드 기반: © 2026 신재원 ,정규환 
I have gotten licensed from these developers.
Github: jaewondeveloper
Repo: https://github.com/jaewondeveloper/automusicplayer
클라우드 연동 확장: 본 저장소

---

*Made with ❤️ for school broadcasting*
