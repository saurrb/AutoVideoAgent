from __future__ import annotations

import argparse
import os
import random
import re
import subprocess
import json
import time
from datetime import datetime
from pathlib import Path

from autovideo.domain.reel_spec import ContentPoint, ReelSpec
from autovideo.services.config_loader import load_page_config
from autovideo.services.content_provider import take_next_batch_from_db, take_next_batch_from_excel
from autovideo.services.state_store import connect
from autovideo.services.video_renderer import render_reel


def _default_ffmpeg(project_root: Path) -> Path:
    return project_root / "tools" / "ffmpeg" / "ffmpeg-8.1.1-essentials_build" / "bin" / "ffmpeg.exe"


def _resolve_state_db_path(project_root: Path, page_key: str) -> Path:
    page_db = project_root / "pages" / page_key / "data" / "state.sqlite3"
    legacy_db = project_root / "data" / "v2" / "state.sqlite3"
    if (not page_db.exists()) and legacy_db.exists():
        page_db.parent.mkdir(parents=True, exist_ok=True)
        page_db.write_bytes(legacy_db.read_bytes())
    return page_db


def _build_reel_spec(page_key: str, cfg: dict, batch) -> ReelSpec:
    style = cfg["style"]
    video = cfg["video"]
    assets = cfg["assets"]
    points = [
        ContentPoint(
            text=row["point_text"],
            highlight_first_words=int(row["highlight_first_words"]),
            source_item_id=int(row["id"]),
        )
        for row in batch.rows
    ]
    return ReelSpec(
        page_key=page_key,
        duration_sec=int(video["duration_sec"]),
        resolution=str(video["resolution"]),
        fps=int(video["fps"]),
        background_color=str(video.get("background", "black")),
        heading_line1=batch.heading_line1,
        heading_line2=batch.heading_line2,
        points=points,
        cta=batch.cta,
        font=str(style["font"]),
        title_font_size=int(style["title_font_size"]),
        body_font_size=int(style["body_font_size"]),
        cta_font_size=int(style["cta_font_size"]),
        highlight_color_ass=str(style["highlight_color_ass"]),
        text_color_ass=str(style["text_color_ass"]),
        outline_color_ass=str(style["outline_color_ass"]),
        header_margin_v=int(style["header_margin_v"]),
        body_margin_v=int(style["body_margin_v"]),
        body_margin_l=int(style.get("body_margin_l", 88)),
        body_margin_r=int(style.get("body_margin_r", 64)),
        point_gap_scale=float(style.get("point_gap_scale", 1.2)),
        cta_pos_x=int(style["cta_pos"][0]),
        cta_pos_y=int(style["cta_pos"][1]),
        logo_path=str(assets["logo_path"]),
        logo_scale_width=int(style["logo_scale_width"]),
        logo_margin_right=int(style["logo_margin_right"]),
        logo_margin_bottom=int(style["logo_margin_bottom"]),
        audio_path=str(assets["audio_path"]),
    )


def _resolve_background_video(project_root: Path, page_key: str, cfg: dict) -> Path:
    render_cfg = cfg.get("render", {})
    cooldown_n = int(render_cfg.get("background_cooldown_n", 2))
    usage_path = project_root / "pages" / page_key / "data" / "background_usage.json"
    recent: list[str] = []
    if usage_path.exists():
        try:
            payload = json.loads(usage_path.read_text(encoding="utf-8"))
            recent = list(payload.get("recent", []))
        except Exception:
            recent = []
    bg_img_dir_rel = render_cfg.get("background_image_dir", "")
    if bg_img_dir_rel:
        bg_img_dir = (project_root / bg_img_dir_rel).resolve()
        if bg_img_dir.exists() and bg_img_dir.is_dir():
            candidates = sorted(
                [
                    p
                    for p in bg_img_dir.iterdir()
                    if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
                ]
            )
            if candidates:
                filtered = [c for c in candidates if str(c) not in recent[:cooldown_n]]
                chosen = random.choice(filtered if filtered else candidates)
                usage_path.parent.mkdir(parents=True, exist_ok=True)
                new_recent = [str(chosen)] + [x for x in recent if x != str(chosen)]
                usage_path.write_text(json.dumps({"recent": new_recent[:max(20, cooldown_n)]}, indent=2), encoding="utf-8")
                return chosen

    bg_dir_rel = render_cfg.get("background_video_dir", "")
    if bg_dir_rel:
        bg_dir = (project_root / bg_dir_rel).resolve()
        if bg_dir.exists() and bg_dir.is_dir():
            candidates = sorted([p for p in bg_dir.iterdir() if p.is_file() and p.suffix.lower() == ".mp4"])
            if candidates:
                filtered = [c for c in candidates if str(c) not in recent[:cooldown_n]]
                chosen = random.choice(filtered if filtered else candidates)
                usage_path.parent.mkdir(parents=True, exist_ok=True)
                new_recent = [str(chosen)] + [x for x in recent if x != str(chosen)]
                usage_path.write_text(json.dumps({"recent": new_recent[:max(20, cooldown_n)]}, indent=2), encoding="utf-8")
                return chosen
    return (project_root / render_cfg["background_video"]).resolve()


def _resolve_audio_path(project_root: Path, cfg: dict) -> Path:
    assets_cfg = cfg.get("assets", {})
    audio_dir_rel = assets_cfg.get("audio_dir", "")
    if audio_dir_rel:
        audio_dir = (project_root / audio_dir_rel).resolve()
        if audio_dir.exists() and audio_dir.is_dir():
            candidates = sorted(
                [p for p in audio_dir.iterdir() if p.is_file() and p.suffix.lower() in {".mp3", ".wav", ".m4a", ".aac"}]
            )
            if candidates:
                return random.choice(candidates)
    return Path(assets_cfg["audio_path"]).resolve()


def _resolve_duration_sec(cfg: dict) -> int:
    video_cfg = cfg.get("video", {})
    return int(video_cfg.get("duration_sec", 10))


def _track_asset_use(conn, page_key: str, asset_path: Path, asset_type: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO assets(page_key,asset_path,asset_type,last_used_at,use_count) VALUES(?,?,?,?,1) "
        "ON CONFLICT(page_key,asset_path) DO UPDATE SET "
        "asset_type=excluded.asset_type,last_used_at=excluded.last_used_at,use_count=assets.use_count+1",
        (page_key, str(asset_path), asset_type, now),
    )
    conn.commit()

def _generate_grok_image(project_root: Path, scene_prompt: str, run_dir: Path, item_id: int) -> Path | None:
    if not scene_prompt.strip():
        return None
    grok = Path.home() / ".grok" / "bin" / "grok.exe"
    if not grok.exists():
        return None

    prompt = (
        scene_prompt.strip()
        + "\n\nCreate strict vertical 9:16 portrait composition, social-media-safe non-explicit styling."
    )
    sess = Path.home() / ".grok" / "sessions"
    start_ts = time.time()
    proc = subprocess.Popen(
        [str(grok), "-p", prompt],
        cwd=project_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    src: Path | None = None
    try:
        while True:
            files = sorted(
                [p for p in sess.rglob("*") if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} and p.stat().st_mtime > (start_ts - 0.5)],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if files:
                src = files[0]
                break
            if proc.poll() is not None:
                break
            time.sleep(2.5)
    finally:
        try:
            if proc.poll() is None:
                proc.terminate()
        except Exception:
            pass

    if not src or (not src.exists()):
        return None

    out_dir = project_root / "pages" / "daily_desire_facts" / "assets" / "backgrounds" / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / f"scene_{item_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{src.suffix.lower()}"
    dst.write_bytes(src.read_bytes())
    return dst


def cmd_render(args: argparse.Namespace) -> None:
    project_root = Path(args.project_root).resolve()
    page_cfg = load_page_config(project_root, args.page)
    cfg = page_cfg.profile
    cfg = dict(cfg)
    cfg["video"] = dict(cfg.get("video", {}))
    cfg["assets"] = dict(cfg.get("assets", {}))

    chosen_duration = _resolve_duration_sec(cfg)
    chosen_audio = _resolve_audio_path(project_root, cfg)
    cfg["video"]["duration_sec"] = chosen_duration
    cfg["assets"]["audio_path"] = str(chosen_audio)

    db_path = _resolve_state_db_path(project_root, args.page)
    conn = connect(db_path)
    provider = str(cfg.get("content", {}).get("provider", "excel")).strip().lower()
    if provider == "db":
        batch = take_next_batch_from_db(
            conn=conn,
            page_key=args.page,
            batch_size=int(cfg["content"].get("batch_size", 5)),
        )
    else:
        batch = take_next_batch_from_excel(
            conn=conn,
            page_key=args.page,
            xlsx_path=(project_root / cfg["content"]["xlsx_path"]).resolve(),
            sheet_name=cfg["content"]["sheet_name"],
            batch_size=int(cfg["content"].get("batch_size", 5)),
        )
    spec = _build_reel_spec(args.page, cfg, batch)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = project_root / "runs" / datetime.now().strftime("%Y-%m-%d") / args.page / run_id
    stem = f"reel_{args.page}_{batch.batch_key}"
    ffmpeg_exe = Path(args.ffmpeg).resolve() if args.ffmpeg else _default_ffmpeg(project_root)
    ass_template = project_root / "scripts" / "reel_template.ass"
    bg_video_path = _resolve_background_video(project_root, args.page, cfg)
    _track_asset_use(conn, args.page, bg_video_path, "background")
    _track_asset_use(conn, args.page, chosen_audio, "audio")
    use_scene_prompt_grok = bool(cfg.get("render", {}).get("use_scene_prompt_grok", False))
    require_scene_prompt_grok = bool(cfg.get("render", {}).get("require_scene_prompt_grok", False))
    if args.page == "daily_desire_facts" and use_scene_prompt_grok and batch.rows:
        scene_prompt = str(batch.rows[0].get("scene_prompt", "")).strip()
        grok_bg = _generate_grok_image(project_root, scene_prompt, run_dir, int(batch.rows[0]["id"]))
        if grok_bg is not None:
            bg_video_path = grok_bg
        elif require_scene_prompt_grok:
            raise RuntimeError("Grok image generation failed for daily_desire_facts and fallback is disabled.")
    bg_video = str(bg_video_path)
    dark_overlay = float(cfg["render"].get("dark_overlay", 0.65))
    render_profile = str(cfg["render"].get("render_profile", "production"))

    ass_path, mp4_path, png_path, manifest_path = render_reel(
        ffmpeg_exe=ffmpeg_exe,
        ass_template_path=ass_template,
        run_dir=run_dir,
        stem=stem,
        spec=spec,
        background_video=bg_video,
        dark_overlay=dark_overlay,
        render_profile=render_profile,
    )
    print(f"PAGE={args.page}")
    print(f"BATCH_IDS={batch.ids}")
    print(f"ASS={ass_path}")
    print(f"MP4={mp4_path}")
    print(f"PNG={png_path}")
    print(f"MANIFEST={manifest_path}")
    print(f"BACKGROUND_VIDEO={bg_video_path}")
    print(f"AUDIO_FILE={chosen_audio}")
    print(f"DURATION_SEC={chosen_duration}")
    print(f"RENDER_PROFILE={render_profile}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--project-root", default=os.getcwd())
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("render")
    r.add_argument("--page", required=True)
    r.add_argument("--ffmpeg", default="")
    r.set_defaults(func=cmd_render)
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
