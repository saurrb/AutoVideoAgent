from __future__ import annotations

import sqlite3
from pathlib import Path


def get_conn(db_file: Path) -> sqlite3.Connection:
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS line_pool (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            line_text TEXT NOT NULL UNIQUE,
            used INTEGER NOT NULL DEFAULT 0,
            used_at TEXT
        );
        CREATE TABLE IF NOT EXISTS reel_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            local_video_path TEXT NOT NULL,
            caption TEXT NOT NULL,
            facebook_video_id TEXT,
            status TEXT NOT NULL
        );
        """
    )
    conn.commit()
