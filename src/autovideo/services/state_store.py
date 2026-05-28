from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS content_items (
  page_key TEXT NOT NULL,
  item_id INTEGER NOT NULL,
  used INTEGER NOT NULL DEFAULT 0,
  used_at TEXT DEFAULT '',
  PRIMARY KEY (page_key, item_id)
);

CREATE TABLE IF NOT EXISTS render_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  page_key TEXT NOT NULL,
  batch_key TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  output_mp4 TEXT NOT NULL,
  output_png TEXT NOT NULL,
  output_ass TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reel_jobs (
  job_id TEXT PRIMARY KEY,
  page_key TEXT NOT NULL,
  run_date TEXT NOT NULL,
  slot TEXT NOT NULL,
  content_id INTEGER NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,
  state TEXT NOT NULL,
  manifest_path TEXT DEFAULT '',
  video_path TEXT DEFAULT '',
  caption TEXT DEFAULT '',
  target_time TEXT DEFAULT '',
  fb_post_id TEXT DEFAULT '',
  retries INTEGER NOT NULL DEFAULT 0,
  error TEXT DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reel_jobs_page_date ON reel_jobs(page_key, run_date);
CREATE INDEX IF NOT EXISTS idx_reel_jobs_state ON reel_jobs(state);

CREATE TABLE IF NOT EXISTS queue_locks (
  page_key TEXT NOT NULL,
  run_date TEXT NOT NULL,
  queue_path TEXT NOT NULL,
  locked_at TEXT NOT NULL,
  PRIMARY KEY (page_key, run_date)
);

CREATE TABLE IF NOT EXISTS content_rows (
  page_key TEXT NOT NULL,
  content_id INTEGER NOT NULL,
  heading TEXT DEFAULT '',
  hook TEXT DEFAULT '',
  reason TEXT DEFAULT '',
  scene_prompt TEXT DEFAULT '',
  updated_at TEXT NOT NULL,
  PRIMARY KEY (page_key, content_id)
);

CREATE TABLE IF NOT EXISTS captions (
  page_key TEXT NOT NULL,
  content_id INTEGER NOT NULL,
  caption TEXT DEFAULT '',
  updated_at TEXT NOT NULL,
  PRIMARY KEY (page_key, content_id)
);

CREATE TABLE IF NOT EXISTS hashtags (
  page_key TEXT NOT NULL,
  content_id INTEGER NOT NULL,
  hashtags TEXT DEFAULT '',
  updated_at TEXT NOT NULL,
  PRIMARY KEY (page_key, content_id)
);

CREATE TABLE IF NOT EXISTS scene_prompts (
  page_key TEXT NOT NULL,
  content_id INTEGER NOT NULL,
  scene_prompt TEXT DEFAULT '',
  updated_at TEXT NOT NULL,
  PRIMARY KEY (page_key, content_id)
);

CREATE TABLE IF NOT EXISTS used_state (
  page_key TEXT NOT NULL,
  content_id INTEGER NOT NULL,
  used INTEGER NOT NULL DEFAULT 0,
  used_at TEXT DEFAULT '',
  PRIMARY KEY (page_key, content_id)
);

CREATE TABLE IF NOT EXISTS assets (
  page_key TEXT NOT NULL,
  asset_path TEXT NOT NULL,
  asset_type TEXT NOT NULL,
  last_used_at TEXT DEFAULT '',
  use_count INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (page_key, asset_path)
);

CREATE TABLE IF NOT EXISTS grok_quota_state (
  page_key TEXT PRIMARY KEY,
  state TEXT NOT NULL DEFAULT 'ok',
  rate_limited_until TEXT DEFAULT '',
  backoff_minutes INTEGER NOT NULL DEFAULT 0,
  last_error TEXT DEFAULT '',
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_kpi (
  run_date TEXT NOT NULL,
  page_key TEXT NOT NULL,
  attempted INTEGER NOT NULL DEFAULT 0,
  generated INTEGER NOT NULL DEFAULT 0,
  scheduled INTEGER NOT NULL DEFAULT 0,
  failed INTEGER NOT NULL DEFAULT 0,
  rate_limit_hits INTEGER NOT NULL DEFAULT 0,
  retries INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (run_date, page_key)
);

CREATE TABLE IF NOT EXISTS content_reservations (
  page_key TEXT NOT NULL,
  run_date TEXT NOT NULL,
  slot TEXT NOT NULL,
  content_id INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'reserved',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (page_key, run_date, slot)
);

CREATE TABLE IF NOT EXISTS content_bank_rows (
  page_key TEXT NOT NULL,
  item_id INTEGER NOT NULL,
  heading_line1 TEXT DEFAULT '',
  heading_line2 TEXT DEFAULT '',
  point_text TEXT DEFAULT '',
  highlight_first_words INTEGER NOT NULL DEFAULT 3,
  cta TEXT DEFAULT '',
  scene_prompt TEXT DEFAULT '',
  caption TEXT DEFAULT '',
  hashtags TEXT DEFAULT '',
  updated_at TEXT NOT NULL,
  PRIMARY KEY (page_key, item_id)
);

CREATE INDEX IF NOT EXISTS idx_content_bank_rows_page_item ON content_bank_rows(page_key, item_id);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn
