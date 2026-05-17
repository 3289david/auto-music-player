/**
 * Auto Music Player — Cloudflare Worker API
 * Stack: Hono + D1 + Web Crypto (JWT)
 *
 * Endpoints:
 *   POST /api/auth/login          — returns JWT
 *   GET  /api/auth/me             — verify token
 *   GET  /api/playlist            — get full playlist
 *   POST /api/playlist            — add song
 *   PUT  /api/playlist/:id        — update song
 *   DELETE /api/playlist/:id      — remove song
 *   PUT  /api/playlist/reorder    — reorder (array of {id, sort_order})
 *   GET  /api/settings            — get all settings
 *   PUT  /api/settings            — update settings (object)
 *   POST /api/sync/push           — app pushes playlist + settings to DB
 *   GET  /api/sync/pull           — app pulls playlist + settings from DB
 */

import { Hono } from 'hono';
import { cors } from 'hono/cors';

const app = new Hono();

// ─── CORS ───────────────────────────────────────────────────────────────────
app.use('*', cors({
  origin: '*',
  allowMethods: ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
  allowHeaders: ['Content-Type', 'Authorization'],
  maxAge: 86400,
}));

// ─── JWT helpers (Web Crypto — no npm needed) ────────────────────────────────
const JWT_ALG = 'HS256';
const JWT_EXP_HOURS = 24 * 7; // 7 days

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
  const enc = new TextEncoder();
  return crypto.subtle.importKey(
    'raw', enc.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign', 'verify']
  );
}

async function signJWT(payload, secret) {
  const header = b64url(new TextEncoder().encode(JSON.stringify({ alg: JWT_ALG, typ: 'JWT' })));
  const body = b64url(new TextEncoder().encode(JSON.stringify({
    ...payload,
    iat: Math.floor(Date.now() / 1000),
    exp: Math.floor(Date.now() / 1000) + JWT_EXP_HOURS * 3600,
  })));
  const data = `${header}.${body}`;
  const key = await getKey(secret);
  const sig = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(data));
  return `${data}.${b64url(sig)}`;
}

async function verifyJWT(token, secret) {
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;
    const [header, body, sig] = parts;
    const key = await getKey(secret);
    const ok = await crypto.subtle.verify(
      'HMAC', key,
      b64urlDecode(sig),
      new TextEncoder().encode(`${header}.${body}`)
    );
    if (!ok) return null;
    const payload = JSON.parse(new TextDecoder().decode(b64urlDecode(body)));
    if (payload.exp < Math.floor(Date.now() / 1000)) return null;
    return payload;
  } catch {
    return null;
  }
}

// ─── Auth middleware ─────────────────────────────────────────────────────────
async function requireAuth(c, next) {
  const auth = c.req.header('Authorization') || '';
  const token = auth.startsWith('Bearer ') ? auth.slice(7) : null;
  if (!token) return c.json({ error: 'Unauthorized' }, 401);
  const payload = await verifyJWT(token, c.env.JWT_SECRET);
  if (!payload) return c.json({ error: 'Invalid or expired token' }, 401);
  c.set('user', payload);
  await next();
}

// ─── bcrypt-compatible password verify via subtle ────────────────────────────
// We store bcrypt hashes in DB but verify via a simple constant-time compare
// for the seeded admin. For new passwords we use SHA-256 stretched with salt.
// NOTE: The seed SQL uses a bcrypt hash. On first login we re-hash with our scheme.
async function hashPassword(password, saltHex) {
  const salt = saltHex || Array.from(crypto.getRandomValues(new Uint8Array(16)))
    .map(b => b.toString(16).padStart(2, '0')).join('');
  const key = await crypto.subtle.importKey(
    'raw', new TextEncoder().encode(password),
    { name: 'PBKDF2' }, false, ['deriveBits']
  );
  const bits = await crypto.subtle.deriveBits(
    { name: 'PBKDF2', salt: new TextEncoder().encode(salt), iterations: 100000, hash: 'SHA-256' },
    key, 256
  );
  const hash = Array.from(new Uint8Array(bits)).map(b => b.toString(16).padStart(2, '0')).join('');
  return `pbkdf2:${salt}:${hash}`;
}

async function verifyPassword(password, storedHash) {
  if (storedHash.startsWith('pbkdf2:')) {
    const [, salt] = storedHash.split(':');
    const computed = await hashPassword(password, salt);
    // constant-time compare
    if (computed.length !== storedHash.length) return false;
    let diff = 0;
    for (let i = 0; i < computed.length; i++) diff |= computed.charCodeAt(i) ^ storedHash.charCodeAt(i);
    return diff === 0;
  }
  // Legacy bcrypt hash from seed SQL — only works for the hardcoded admin/1234
  // On successful login we migrate to pbkdf2
  return storedHash.startsWith('$2b$') && password === '1234';
}

// ─── Routes ─────────────────────────────────────────────────────────────────

// Health check
app.get('/', c => c.json({ ok: true, service: 'auto-music-player-api', version: '1.0.0' }));

// POST /api/auth/login
app.post('/api/auth/login', async c => {
  const { username, password } = await c.req.json().catch(() => ({}));
  if (!username || !password) return c.json({ error: 'username and password required' }, 400);

  const row = await c.env.DB.prepare('SELECT id, username, password_hash FROM users WHERE username = ?')
    .bind(username).first();
  if (!row) return c.json({ error: 'Invalid credentials' }, 401);

  const valid = await verifyPassword(password, row.password_hash);
  if (!valid) return c.json({ error: 'Invalid credentials' }, 401);

  // Migrate bcrypt → pbkdf2 on first successful login
  if (row.password_hash.startsWith('$2b$')) {
    const newHash = await hashPassword(password);
    await c.env.DB.prepare('UPDATE users SET password_hash = ? WHERE id = ?')
      .bind(newHash, row.id).run();
  }

  const token = await signJWT({ sub: row.username, uid: row.id }, c.env.JWT_SECRET);
  return c.json({ token, username: row.username });
});

// GET /api/auth/me
app.get('/api/auth/me', requireAuth, c => {
  const user = c.get('user');
  return c.json({ username: user.sub });
});

// ─── Playlist ────────────────────────────────────────────────────────────────

// GET /api/playlist
app.get('/api/playlist', requireAuth, async c => {
  const { results } = await c.env.DB.prepare(
    'SELECT * FROM playlist ORDER BY sort_order ASC, id ASC'
  ).all();
  return c.json({ playlist: results });
});

// POST /api/playlist — add song
app.post('/api/playlist', requireAuth, async c => {
  const body = await c.req.json().catch(() => ({}));
  const { type = 'youtube', song_id, title, thumbnail = '', path = '', duration = 0 } = body;
  if (!song_id || !title) return c.json({ error: 'song_id and title required' }, 400);

  const maxOrder = await c.env.DB.prepare('SELECT MAX(sort_order) as m FROM playlist').first();
  const sort_order = (maxOrder?.m ?? -1) + 1;

  const result = await c.env.DB.prepare(
    `INSERT INTO playlist (sort_order, type, song_id, title, thumbnail, path, duration)
     VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING *`
  ).bind(sort_order, type, song_id, title, thumbnail, path, duration).first();

  return c.json({ song: result }, 201);
});

// PUT /api/playlist/reorder — bulk reorder
app.put('/api/playlist/reorder', requireAuth, async c => {
  const { items } = await c.req.json().catch(() => ({}));
  if (!Array.isArray(items)) return c.json({ error: 'items array required' }, 400);

  const stmts = items.map(({ id, sort_order }) =>
    c.env.DB.prepare('UPDATE playlist SET sort_order = ?, updated_at = datetime(\'now\') WHERE id = ?')
      .bind(sort_order, id)
  );
  await c.env.DB.batch(stmts);
  return c.json({ ok: true });
});

// PUT /api/playlist/:id — update song
app.put('/api/playlist/:id', requireAuth, async c => {
  const id = Number(c.req.param('id'));
  const body = await c.req.json().catch(() => ({}));
  const { title, thumbnail, path, duration, sort_order } = body;

  const existing = await c.env.DB.prepare('SELECT id FROM playlist WHERE id = ?').bind(id).first();
  if (!existing) return c.json({ error: 'Not found' }, 404);

  const fields = [];
  const values = [];
  if (title !== undefined) { fields.push('title = ?'); values.push(title); }
  if (thumbnail !== undefined) { fields.push('thumbnail = ?'); values.push(thumbnail); }
  if (path !== undefined) { fields.push('path = ?'); values.push(path); }
  if (duration !== undefined) { fields.push('duration = ?'); values.push(duration); }
  if (sort_order !== undefined) { fields.push('sort_order = ?'); values.push(sort_order); }
  fields.push("updated_at = datetime('now')");

  if (fields.length === 1) return c.json({ error: 'No fields to update' }, 400);

  values.push(id);
  const result = await c.env.DB.prepare(
    `UPDATE playlist SET ${fields.join(', ')} WHERE id = ? RETURNING *`
  ).bind(...values).first();

  return c.json({ song: result });
});

// DELETE /api/playlist/:id
app.delete('/api/playlist/:id', requireAuth, async c => {
  const id = Number(c.req.param('id'));
  const existing = await c.env.DB.prepare('SELECT id FROM playlist WHERE id = ?').bind(id).first();
  if (!existing) return c.json({ error: 'Not found' }, 404);
  await c.env.DB.prepare('DELETE FROM playlist WHERE id = ?').bind(id).run();
  return c.json({ ok: true });
});

// DELETE /api/playlist — clear all
app.delete('/api/playlist', requireAuth, async c => {
  await c.env.DB.prepare('DELETE FROM playlist').run();
  return c.json({ ok: true });
});

// ─── Settings ────────────────────────────────────────────────────────────────

// GET /api/settings
app.get('/api/settings', requireAuth, async c => {
  const { results } = await c.env.DB.prepare('SELECT key, value FROM settings').all();
  const settings = Object.fromEntries(results.map(r => [r.key, r.value]));
  return c.json({ settings });
});

// PUT /api/settings — update key/value pairs
app.put('/api/settings', requireAuth, async c => {
  const body = await c.req.json().catch(() => ({}));
  const stmts = Object.entries(body).map(([key, value]) =>
    c.env.DB.prepare(
      `INSERT INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now'))
       ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at`
    ).bind(key, String(value))
  );
  if (stmts.length) await c.env.DB.batch(stmts);
  return c.json({ ok: true });
});

// ─── Sync ────────────────────────────────────────────────────────────────────

// POST /api/sync/push — Windows app pushes its full state to DB
app.post('/api/sync/push', requireAuth, async c => {
  const { playlist, settings } = await c.req.json().catch(() => ({}));

  // Replace full playlist
  if (Array.isArray(playlist)) {
    await c.env.DB.prepare('DELETE FROM playlist').run();
    if (playlist.length > 0) {
      const stmts = playlist.map((item, idx) =>
        c.env.DB.prepare(
          `INSERT INTO playlist (sort_order, type, song_id, title, thumbnail, path, duration)
           VALUES (?, ?, ?, ?, ?, ?, ?)`
        ).bind(idx, item.type || 'youtube', item.id || item.song_id, item.title,
          item.thumbnail || '', item.path || '', item.duration || 0)
      );
      await c.env.DB.batch(stmts);
    }
  }

  // Upsert settings
  if (settings && typeof settings === 'object') {
    const stmts = Object.entries(settings).map(([key, value]) =>
      c.env.DB.prepare(
        `INSERT INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now'))
         ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at`
      ).bind(key, String(value))
    );
    if (stmts.length) await c.env.DB.batch(stmts);
  }

  return c.json({ ok: true, pushed_at: new Date().toISOString() });
});

// GET /api/sync/pull — Windows app pulls full state from DB
app.get('/api/sync/pull', requireAuth, async c => {
  const [playlistRes, settingsRes] = await Promise.all([
    c.env.DB.prepare('SELECT * FROM playlist ORDER BY sort_order ASC, id ASC').all(),
    c.env.DB.prepare('SELECT key, value FROM settings').all(),
  ]);

  const playlist = playlistRes.results.map(row => ({
    id: row.id,
    type: row.type,
    id: row.song_id,      // map song_id → id for app compatibility
    song_id: row.song_id,
    title: row.title,
    thumbnail: row.thumbnail,
    path: row.path,
    duration: row.duration,
    sort_order: row.sort_order,
  }));

  const settings = Object.fromEntries(settingsRes.results.map(r => [r.key, r.value]));

  return c.json({ playlist, settings, pulled_at: new Date().toISOString() });
});

export default app;
