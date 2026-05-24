from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def seed_lines(conn: sqlite3.Connection, lines_file: Path) -> int:
    if not lines_file.exists():
        raise FileNotFoundError(f"Lines file not found: {lines_file}")
    lines = []
    for raw in lines_file.read_text(encoding="utf-8").splitlines():
        cleaned = raw.lstrip("\ufeff").strip()
        if cleaned:
            lines.append(cleaned)
    conn.executemany(
        "INSERT OR IGNORE INTO line_pool(line_text) VALUES(?)",
        [(line,) for line in lines],
    )
    conn.commit()
    return len(lines)


def pick_lines(conn: sqlite3.Connection, n: int = 5) -> list[str]:
    rows = conn.execute(
        "SELECT id, line_text FROM line_pool WHERE used = 0 ORDER BY id LIMIT ?",
        (n,),
    ).fetchall()
    if len(rows) < n:
        raise RuntimeError("Not enough unused lines. Add more lines and reseed.")
    ids = [r["id"] for r in rows]
    now = datetime.now(timezone.utc).isoformat()
    conn.executemany(
        "UPDATE line_pool SET used = 1, used_at = ? WHERE id = ?",
        [(now, row_id) for row_id in ids],
    )
    conn.commit()
    return [r["line_text"] for r in rows]
