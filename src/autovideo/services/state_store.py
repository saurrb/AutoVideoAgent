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
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn
