from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.config import Settings
from app.facebook import publish_facebook_reel
from app.lines import pick_lines
from app.render import render_black_reel


def run_once(conn: sqlite3.Connection, settings: Settings) -> Path:
    lines = pick_lines(conn, 5)
    now = datetime.now(timezone.utc)
    out_file = settings.output_dir / f"reel_{now.strftime('%Y%m%d_%H%M%S')}.mp4"
    caption = " | ".join(lines)
    render_black_reel(
        ffmpeg_exe=settings.ffmpeg_exe,
        out_file=out_file,
        lines=lines,
        music_file=settings.music_file,
        font_file=settings.font_file,
        logo_file=settings.logo_file,
    )

    status = "rendered"
    fb_video_id = None
    if settings.post_to_facebook:
        fb_video_id = publish_facebook_reel(settings.meta_config_file, out_file, caption)
        status = "posted"

    conn.execute(
        "INSERT INTO reel_posts(created_at, local_video_path, caption, facebook_video_id, status) VALUES(?,?,?,?,?)",
        (now.isoformat(), str(out_file), caption, fb_video_id, status),
    )
    conn.commit()
    return out_file
