-- Auto Music Player — D1 Schema
-- Run: wrangler d1 execute auto-music-player-db --file=schema.sql

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS playlist (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sort_order INTEGER NOT NULL DEFAULT 0,
  type TEXT NOT NULL DEFAULT 'youtube',   -- 'youtube' | 'local'
  song_id TEXT NOT NULL,                  -- YouTube video ID or local filename
  title TEXT NOT NULL,
  thumbnail TEXT DEFAULT '',
  path TEXT DEFAULT '',                   -- local file relative path
  duration REAL DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT DEFAULT (datetime('now'))
);

-- Seed admin account (password: 1234, bcrypt hash)
-- Generated with: bcrypt.hashpw(b'1234', bcrypt.gensalt(rounds=10))
INSERT OR IGNORE INTO users (username, password_hash)
VALUES ('admin', '$2b$10$N9qo8uLOickgx2ZMRZoMyeIjZAgcfl7p92ldGxad68LFkFh6v0d6e');

-- Default settings
INSERT OR IGNORE INTO settings (key, value) VALUES ('end_broadcast_image', '');
INSERT OR IGNORE INTO settings (key, value) VALUES ('autostart', 'false');
INSERT OR IGNORE INTO settings (key, value) VALUES ('broadcast_browser', 'auto');
INSERT OR IGNORE INTO settings (key, value) VALUES ('port', '8765');
