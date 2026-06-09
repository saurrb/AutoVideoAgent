from __future__ import annotations

import sqlite3
from datetime import datetime


def pick_next_dragon_row(conn: sqlite3.Connection, page_key: str) -> dict:
    row = conn.execute(
        "SELECT item_id, point_text, caption, hashtags "
        "FROM content_bank_rows "
        "WHERE page_key=? "
        "AND item_id NOT IN (SELECT item_id FROM content_items WHERE page_key=? AND used=1) "
        "AND item_id NOT IN (SELECT content_id FROM used_state WHERE page_key=? AND used=1) "
        "ORDER BY item_id ASC LIMIT 1",
        (page_key, page_key, page_key),
    ).fetchone()
    if not row:
        raise RuntimeError("No unused dragon DB rows left.")

    item_id = int(row[0])
    point_text = str(row[1] or "").strip()
    caption = str(row[2] or "").strip()
    hashtags = str(row[3] or "").strip()
    scene_a_prompt, scene_b_prompt = (point_text.split("||", 1) + [""])[:2]
    scene_a_prompt = scene_a_prompt.strip()
    scene_b_prompt = scene_b_prompt.strip()
    now = datetime.utcnow().isoformat()

    conn.execute(
        "INSERT INTO content_items(page_key,item_id,used,used_at) VALUES(?,?,1,?) "
        "ON CONFLICT(page_key,item_id) DO UPDATE SET used=1,used_at=excluded.used_at",
        (page_key, item_id, now),
    )
    conn.execute(
        "INSERT INTO used_state(page_key,content_id,used,used_at) VALUES(?,?,1,?) "
        "ON CONFLICT(page_key,content_id) DO UPDATE SET used=1,used_at=excluded.used_at",
        (page_key, item_id, now),
    )
    conn.commit()

    return {
        "id": item_id,
        "heading": f"Dragon Scene {item_id}",
        "scene_a_prompt": scene_a_prompt,
        "scene_b_prompt": scene_b_prompt or scene_a_prompt,
        "scene_a_duration_sec": 15,
        "scene_b_duration_sec": 15,
        "target_resolution": "720p",
        "target_aspect_ratio": "9:16",
        "caption": caption,
        "hashtags": hashtags,
    }
