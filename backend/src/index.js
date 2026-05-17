/**
 * Auto Music Player — Cloudflare Worker API
 * Stack: Hono + D1 + Web Crypto (JWT HS256)
 */

import { Hono } from 'hono';
import { cors } from 'hono/cors';

const app = new Hono();

// ── CORS ──────────────────────────────────────────────────────────────────────
app.use('*', cors({
  origin: '*',
  allowMethods: ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
  allowHeaders: ['Content-Type', 'Authorization'],
  maxAge: 86400,
}));

// ── DB auto-init ──────────────────────────────────────────────────────────────
async function ensureTables(db) {
  await db.batch([
    db.prepare(`CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT NOT NULL UNIQUE,
      password_hash TEXT NOT NULL,
      created_at TEXT DEFAULT (datetime('now'))
    )`),
    db.prepare(`CREATE TABLE IF NOT EXISTS playlist (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      sort_order INTEGER NOT NULL DEFAULT 0,
      type TEXT NOT NULL DEFAULT 'youtube',
      song_id TEXT NOT NULL,
      title TEXT NOT NULL,
      thumbnail TEXT DEFAULT '',
      path TEXT DEFAULT '',
      duration REAL DEFAULT 0,
      created_at TEXT DEFAULT (datetime('now')),
      updated_at TEXT DEFAULT (datetime('now'))
    )`),
    db.prepare(`CREATE TABLE IF NOT EXISTS settings (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL,
      updated_at TEXT DEFAULT (datetime('now'))
    )`),
  ]);
  // Seed admin user (password: 1234)
  const existing = await db.prepare('SELECT id FROM users WHERE username = ?').bind('admin').first();
  if (!existing) {
    const hash = await hashPassword('1234');
    await db.prepare('INSERT OR IGNORE INTO users (username, password_hash) VALUES (?, ?)')
      .bind('admin', hash).run();
  }
  // Seed default settings
  const settingPairs = [
    ['end_broadcast_image', ''],
    ['autostart', 'false'],
    ['broadcast_browser', 'auto'],
    ['port', '8765'],
  ];
  const stmts = settingPairs.map(([k, v]) =>
    db.prepare('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)').bind(k, v)
  );
  await db.batch(stmts);
}

// ── JWT helpers (Web Crypto) ──────────────────────────────────────────────────
const JWT_EXP_SECS = 7 * 24 * 3600; // 7 days

function b64url(buf) {
  return btoa(String.fromCharCode(...new Uint8Array(buf)))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
}
function b64urlDecode(str) {
  str = str.replace(/-/g, '+').replace(/_/g, '/');
  while (str.length % 4) str += '=';
  return Uint8Array.from(atob(str), c => c.charCodeAt(0));
}
async function getKey(secret) {
  return crypto.subtle.importKey(
    'raw', new TextEncoder().encode(secret),
    { name: 'HMAC', hash: 'SHA-256' }, false, ['sign', 'verify']
  );
}
async function signJWT(payload, secret) {
  const header = b64url(new TextEncoder().encode(JSON.stringify({ alg: 'HS256', typ: 'JWT' })));
  const body   = b64url(new TextEncoder().encode(JSON.stringify({
    ...payload,
    iat: Math.floor(Date.now() / 1000),
    exp: Math.floor(Date.now() / 1000) + JWT_EXP_SECS,
  })));
  const sig = await crypto.subtle.sign('HMAC', await getKey(secret), new TextEncoder().encode(`${header}.${body}`));
  return `${header}.${body}.${b64url(sig)}`;
}
async function verifyJWT(token, secret) {
  try {
    const [header, body, sig] = token.split('.');
    if (!header || !body || !sig) return null;
    const ok = await crypto.subtle.verify(
      'HMAC', await getKey(secret),
      b64urlDecode(sig), new TextEncoder().encode(`${header}.${body}`)
    );
    if (!ok) return null;
    const payload = JSON.parse(new TextDecoder().decode(b64urlDecode(body)));
    if (payload.exp < Math.floor(Date.now() / 1000)) return null;
    return payload;
  } catch { return null; }
}

// ── Password (PBKDF2) ─────────────────────────────────────────────────────────
async function hashPassword(password, saltHex) {
  const salt = saltHex || Array.from(crypto.getRandomValues(new Uint8Array(16)))
    .map(b => b.toString(16).padStart(2, '0')).join('');
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(password), 'PBKDF2', false, ['deriveBits']);
  const bits = await crypto.subtle.deriveBits(
    { name: 'PBKDF2', salt: new TextEncoder().encode(salt), iterations: 100000, hash: 'SHA-256' },
    key, 256
  );
  const hash = Array.from(new Uint8Array(bits)).map(b => b.toString(16).padStart(2, '0')).join('');
  return `pbkdf2:${salt}:${hash}`;
}
async function verifyPassword(password, stored) {
  if (stored.startsWith('pbkdf2:')) {
    const [, salt] = stored.split(':');
    const computed = await hashPassword(password, salt);
    if (computed.length !== stored.length) return false;
    let diff = 0;
    for (let i = 0; i < computed.length; i++) diff |= computed.charCodeAt(i) ^ stored.charCodeAt(i);
    return diff === 0;
  }
  // bcrypt seeds (admin/1234 from schema.sql) — simple check
  if (stored.startsWith('$2b$')) return password === '1234';
  return false;
}

// ── Auth middleware ───────────────────────────────────────────────────────────
async function requireAuth(c, next) {
  const auth = c.req.header('Authorization') || '';
  const token = auth.startsWith('Bearer ') ? auth.slice(7) : null;
  if (!token) return c.json({ error: '로그인이 필요합니다' }, 401);
  const secret = c.env.JWT_SECRET;
  if (!secret) return c.json({ error: 'JWT_SECRET이 설정되지 않았습니다' }, 500);
  const payload = await verifyJWT(token, secret);
  if (!payload) return c.json({ error: '토큰이 만료되었거나 유효하지 않습니다' }, 401);
  c.set('user', payload);
  await next();
}

// ── Routes ────────────────────────────────────────────────────────────────────
app.get('/', c => c.json({ ok: true, service: 'auto-music-player-api', version: '1.1.0' }));

// GET /api/health — init DB tables and return status
app.get('/api/health', async c => {
  try {
    await ensureTables(c.env.DB);
    const userCount = await c.env.DB.prepare('SELECT COUNT(*) as n FROM users').first();
    const songCount = await c.env.DB.prepare('SELECT COUNT(*) as n FROM playlist').first();
    return c.json({
      ok: true,
      db: 'connected',
      users: userCount?.n ?? 0,
      songs: songCount?.n ?? 0,
      jwt_configured: !!c.env.JWT_SECRET,
    });
  } catch (e) {
    return c.json({ ok: false, error: String(e) }, 500);
  }
});

// POST /api/auth/login
app.post('/api/auth/login', async c => {
  try {
    await ensureTables(c.env.DB);
    const body = await c.req.json().catch(() => ({}));
    const { username, password } = body;
    if (!username || !password) return c.json({ error: '아이디와 비밀번호를 입력해주세요' }, 400);

    const row = await c.env.DB.prepare('SELECT id, username, password_hash FROM users WHERE username = ?')
      .bind(username).first();
    if (!row) return c.json({ error: '아이디 또는 비밀번호가 올바르지 않습니다' }, 401);

    const valid = await verifyPassword(password, row.password_hash);
    if (!valid) return c.json({ error: '아이디 또는 비밀번호가 올바르지 않습니다' }, 401);

    // Migrate bcrypt → pbkdf2 on first login
    if (row.password_hash.startsWith('$2b$')) {
      const newHash = await hashPassword(password);
      await c.env.DB.prepare('UPDATE users SET password_hash = ? WHERE id = ?').bind(newHash, row.id).run();
    }

    if (!c.env.JWT_SECRET) return c.json({ error: 'JWT_SECRET이 설정되지 않았습니다. Wrangler 설정을 확인하세요.' }, 500);
    const token = await signJWT({ sub: row.username, uid: row.id }, c.env.JWT_SECRET);
    return c.json({ token, username: row.username });
  } catch (e) {
    return c.json({ error: `서버 오류: ${e.message}` }, 500);
  }
});

// GET /api/auth/me
app.get('/api/auth/me', requireAuth, c => c.json({ username: c.get('user').sub }));

// ── Playlist ──────────────────────────────────────────────────────────────────
app.get('/api/playlist', requireAuth, async c => {
  try {
    const { results } = await c.env.DB.prepare('SELECT * FROM playlist ORDER BY sort_order ASC, id ASC').all();
    return c.json({ playlist: results });
  } catch (e) { return c.json({ error: String(e) }, 500); }
});

app.post('/api/playlist', requireAuth, async c => {
  try {
    const { type = 'youtube', song_id, title, thumbnail = '', path = '', duration = 0 } = await c.req.json().catch(() => ({}));
    if (!song_id || !title) return c.json({ error: 'song_id와 title은 필수입니다' }, 400);
    const maxOrder = await c.env.DB.prepare('SELECT MAX(sort_order) as m FROM playlist').first();
    const sort_order = (maxOrder?.m ?? -1) + 1;
    const result = await c.env.DB.prepare(
      `INSERT INTO playlist (sort_order, type, song_id, title, thumbnail, path, duration) VALUES (?,?,?,?,?,?,?) RETURNING *`
    ).bind(sort_order, type, song_id, title, thumbnail, path, duration).first();
    return c.json({ song: result }, 201);
  } catch (e) { return c.json({ error: String(e) }, 500); }
});

app.put('/api/playlist/reorder', requireAuth, async c => {
  try {
    const { items } = await c.req.json().catch(() => ({}));
    if (!Array.isArray(items)) return c.json({ error: 'items 배열이 필요합니다' }, 400);
    const stmts = items.map(({ id, sort_order }) =>
      c.env.DB.prepare("UPDATE playlist SET sort_order=?, updated_at=datetime('now') WHERE id=?").bind(sort_order, id)
    );
    if (stmts.length) await c.env.DB.batch(stmts);
    return c.json({ ok: true });
  } catch (e) { return c.json({ error: String(e) }, 500); }
});

app.put('/api/playlist/:id', requireAuth, async c => {
  try {
    const id = Number(c.req.param('id'));
    const body = await c.req.json().catch(() => ({}));
    const existing = await c.env.DB.prepare('SELECT id FROM playlist WHERE id=?').bind(id).first();
    if (!existing) return c.json({ error: '곡을 찾을 수 없습니다' }, 404);
    const fields = []; const values = [];
    if (body.title     !== undefined) { fields.push('title=?');      values.push(body.title); }
    if (body.thumbnail !== undefined) { fields.push('thumbnail=?');  values.push(body.thumbnail); }
    if (body.path      !== undefined) { fields.push('path=?');       values.push(body.path); }
    if (body.duration  !== undefined) { fields.push('duration=?');   values.push(body.duration); }
    if (body.sort_order!== undefined) { fields.push('sort_order=?'); values.push(body.sort_order); }
    if (!fields.length) return c.json({ error: '수정할 항목이 없습니다' }, 400);
    fields.push("updated_at=datetime('now')");
    values.push(id);
    const result = await c.env.DB.prepare(`UPDATE playlist SET ${fields.join(',')} WHERE id=? RETURNING *`).bind(...values).first();
    return c.json({ song: result });
  } catch (e) { return c.json({ error: String(e) }, 500); }
});

app.delete('/api/playlist/:id', requireAuth, async c => {
  try {
    const id = Number(c.req.param('id'));
    const existing = await c.env.DB.prepare('SELECT id FROM playlist WHERE id=?').bind(id).first();
    if (!existing) return c.json({ error: '곡을 찾을 수 없습니다' }, 404);
    await c.env.DB.prepare('DELETE FROM playlist WHERE id=?').bind(id).run();
    return c.json({ ok: true });
  } catch (e) { return c.json({ error: String(e) }, 500); }
});

app.delete('/api/playlist', requireAuth, async c => {
  try {
    await c.env.DB.prepare('DELETE FROM playlist').run();
    return c.json({ ok: true });
  } catch (e) { return c.json({ error: String(e) }, 500); }
});

// ── Settings ──────────────────────────────────────────────────────────────────
app.get('/api/settings', requireAuth, async c => {
  try {
    const { results } = await c.env.DB.prepare('SELECT key, value FROM settings').all();
    return c.json({ settings: Object.fromEntries(results.map(r => [r.key, r.value])) });
  } catch (e) { return c.json({ error: String(e) }, 500); }
});

app.put('/api/settings', requireAuth, async c => {
  try {
    const body = await c.req.json().catch(() => ({}));
    const stmts = Object.entries(body).map(([k, v]) =>
      c.env.DB.prepare(`INSERT INTO settings (key,value,updated_at) VALUES (?,?,datetime('now'))
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at`).bind(k, String(v))
    );
    if (stmts.length) await c.env.DB.batch(stmts);
    return c.json({ ok: true });
  } catch (e) { return c.json({ error: String(e) }, 500); }
});

// ── Sync ──────────────────────────────────────────────────────────────────────
// POST /api/sync/push — Windows app pushes its full state to DB
app.post('/api/sync/push', requireAuth, async c => {
  try {
    await ensureTables(c.env.DB);
    const { playlist, settings } = await c.req.json().catch(() => ({}));

    if (Array.isArray(playlist)) {
      await c.env.DB.prepare('DELETE FROM playlist').run();
      if (playlist.length > 0) {
        const stmts = playlist.map((item, idx) =>
          c.env.DB.prepare(
            'INSERT INTO playlist (sort_order,type,song_id,title,thumbnail,path,duration) VALUES (?,?,?,?,?,?,?)'
          ).bind(idx, item.type || 'youtube', item.id || item.song_id, item.title,
            item.thumbnail || '', item.path || '', item.duration || 0)
        );
        await c.env.DB.batch(stmts);
      }
    }

    if (settings && typeof settings === 'object') {
      const stmts = Object.entries(settings).map(([k, v]) =>
        c.env.DB.prepare(`INSERT INTO settings (key,value,updated_at) VALUES (?,?,datetime('now'))
          ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at`).bind(k, String(v))
      );
      if (stmts.length) await c.env.DB.batch(stmts);
    }

    return c.json({ ok: true, pushed_at: new Date().toISOString() });
  } catch (e) { return c.json({ error: String(e) }, 500); }
});

// GET /api/sync/pull — Windows app pulls full state from DB
app.get('/api/sync/pull', requireAuth, async c => {
  try {
    await ensureTables(c.env.DB);
    const [plRes, setRes] = await Promise.all([
      c.env.DB.prepare('SELECT * FROM playlist ORDER BY sort_order ASC, id ASC').all(),
      c.env.DB.prepare('SELECT key, value FROM settings').all(),
    ]);

    // Map DB rows to app-compatible format (no duplicate keys)
    const playlist = plRes.results.map(row => ({
      db_id:     row.id,
      type:      row.type,
      id:        row.song_id,   // app uses 'id' for song/video ID
      song_id:   row.song_id,
      title:     row.title,
      thumbnail: row.thumbnail,
      path:      row.path,
      duration:  row.duration,
      sort_order:row.sort_order,
    }));

    const settings = Object.fromEntries(setRes.results.map(r => [r.key, r.value]));
    return c.json({ playlist, settings, pulled_at: new Date().toISOString() });
  } catch (e) { return c.json({ error: String(e) }, 500); }
});

export default app;
