from __future__ import annotations

import json
import math
import os
import random
import re
import subprocess
import sys
import time
import traceback
from dataclasses import asdict
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any

from .common import (
    PROJECT_ROOT,
    build_slot_dir,
    get_page_runtime,
    load_module,
    read_json,
    run_checked,
    run_meta_upload,
    send_status,
    write_json,
    _wsl_to_windows_path,
)

SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autovideo.app.cli import (  # noqa: E402
    _build_reel_spec,
    _default_ffmpeg,
    _resolve_audio_path,
    _resolve_background_video,
    _resolve_duration_sec,
    _resolve_state_db_path,
    _track_asset_use,
)
from autovideo.domain.reel_spec import ContentPoint, ReelSpec  # noqa: E402
from autovideo.services.config_loader import load_page_config  # noqa: E402
from autovideo.services.content_provider import take_next_batch_from_db, take_next_batch_from_excel  # noqa: E402
from autovideo.services.caption_builder import build_caption  # noqa: E402
from autovideo.services.state_store import connect  # noqa: E402
from autovideo.services.video_renderer import render_reel  # noqa: E402
from autovideo.services.grok_cli import is_grok_credit_error, resolve_grok_exe, run_grok_text  # noqa: E402
from autovideo.services.text_utils import extract_json_object, normalize_payload, normalize_text, repair_mojibake, sanitize_text_list  # noqa: E402

PAGE4_PREP = load_module(
    "airflow_page4_prepare", PROJECT_ROOT / "pages" / "page4_relationship" / "prepare_page4_narration_and_scenes.py"
)

FFPROBE_EXE = PROJECT_ROOT / "tools" / "ffmpeg" / "ffmpeg-8.1.1-essentials_build" / "bin" / "ffprobe.exe"
ASS_TEMPLATE = PROJECT_ROOT / "scripts" / "templates" / "reel_template.ass"


def _is_failed_payload(payload: dict[str, Any]) -> bool:
    return bool(payload.get("failed"))


def _request_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    request = payload.get("request")
    if isinstance(request, dict):
        return request
    return payload


def _slot_dir_from_payload(payload: dict[str, Any], request: dict[str, Any]) -> Path:
    if payload.get("slot_dir"):
        return Path(payload["slot_dir"])
    if request.get("run_root"):
        return build_slot_dir(Path(request["run_root"]), request)
    return PROJECT_ROOT / "runs" / "airflow_ui" / str(request.get("page_key", "unknown")) / "failed_unknown"


def _is_grok_credit_error(text: str) -> bool:
    return is_grok_credit_error(text)


def _format_stage_error(stage: str, exc: BaseException) -> tuple[str, str]:
    error = f"{type(exc).__name__}: {exc}"
    if _is_grok_credit_error(error):
        return (
            f"{stage}_grok_credits",
            "GROK_CREDITS_EXHAUSTED: Grok returned 403 spending/subscription limit. "
            "Add credits or renew SuperGrok, then rerun the missed slots.",
        )
    return stage, error


def _failed_payload(source: dict[str, Any], stage: str, exc: BaseException) -> dict[str, Any]:
    request = _request_from_payload(source)
    slot_dir = _slot_dir_from_payload(source, request)
    page_key = str(source.get("page_key") or request.get("page_key") or "unknown")
    failed_stage, error = _format_stage_error(stage, exc)
    payload = {
        **source,
        "request": request,
        "page_key": page_key,
        "slot_dir": str(slot_dir),
        "failed": True,
        "failed_stage": failed_stage,
        "error": error,
        "traceback": traceback.format_exc(),
    }
    write_json(slot_dir / f"failed_{failed_stage}.json", payload)
    return payload


def _stage_guard(stage: str):
    def decorator(func):
        @wraps(func)
        def wrapper(payload: dict[str, Any]) -> dict[str, Any]:
            if _is_failed_payload(payload):
                return payload
            try:
                return func(payload)
            except Exception as exc:
                return _failed_payload(payload, stage, exc)

        return wrapper

    return decorator


def _write_slot_complete(request: dict[str, Any], payload: dict[str, Any], status: str) -> None:
    if request.get("slot_complete_path"):
        write_json(
            Path(request["slot_complete_path"]),
            {
                "status": status,
                "page_key": payload.get("page_key", request.get("page_key", "")),
                "slot": request.get("slot", ""),
                "target_iso": request.get("target_iso", ""),
                "failed_stage": payload.get("failed_stage", ""),
                "error": payload.get("error", ""),
                "completed_at": datetime.utcnow().isoformat(),
            },
        )


def _slot_meta(request: dict[str, Any]) -> tuple[dict[str, Any], Path, str]:
    runtime = get_page_runtime(str(request["page_key"]))
    run_root = Path(request["run_root"])
    slot_dir = build_slot_dir(run_root, request)
    asset_id = str(runtime.get("facebook_asset_id", "")).strip()
    if not asset_id:
        raise RuntimeError(f"Missing facebook_asset_id for {request['page_key']}")
    return runtime, slot_dir, asset_id


def _spec_from_dict(data: dict[str, Any]) -> ReelSpec:
    payload = dict(data)
    payload["points"] = [ContentPoint(**point) for point in payload["points"]]
    return ReelSpec(**payload)


@_stage_guard("prepare_content")
def page12_prepare_slot(request: dict[str, Any]) -> dict[str, Any]:
    page_key = str(request["page_key"])
    _, slot_dir, asset_id = _slot_meta(request)
    cfg = load_page_config(PROJECT_ROOT, page_key).profile
    cfg = dict(cfg)
    cfg["video"] = dict(cfg.get("video", {}))
    cfg["assets"] = dict(cfg.get("assets", {}))
    cfg["render"] = dict(cfg.get("render", {}))

    chosen_duration = _resolve_duration_sec(cfg)
    chosen_audio = _resolve_audio_path(PROJECT_ROOT, cfg)
    cfg["video"]["duration_sec"] = chosen_duration
    cfg["assets"]["audio_path"] = str(chosen_audio)

    db_path = _resolve_state_db_path(PROJECT_ROOT, page_key)
    conn = connect(db_path)
    provider = str(cfg.get("content", {}).get("provider", "excel")).strip().lower()
    if provider == "db":
        batch = take_next_batch_from_db(conn=conn, page_key=page_key, batch_size=int(cfg["content"].get("batch_size", 5)))
    else:
        batch = take_next_batch_from_excel(
            conn=conn,
            page_key=page_key,
            xlsx_path=(PROJECT_ROOT / cfg["content"]["xlsx_path"]).resolve(),
            sheet_name=cfg["content"]["sheet_name"],
            batch_size=int(cfg["content"].get("batch_size", 5)),
        )

    spec = _build_reel_spec(page_key, cfg, batch)
    ffmpeg_exe = _default_ffmpeg(PROJECT_ROOT)
    bg_path = _resolve_background_video(PROJECT_ROOT, page_key, cfg)
    _track_asset_use(conn, page_key, bg_path, "background")
    _track_asset_use(conn, page_key, chosen_audio, "audio")

    payload = {
        "request": request,
        "page_key": page_key,
        "asset_id": asset_id,
        "slot_dir": str(slot_dir),
        "batch_ids": batch.ids,
        "batch_key": batch.batch_key,
        "duration_sec": chosen_duration,
        "audio_path": str(chosen_audio),
        "background_path": str(bg_path),
        "dark_overlay": float(cfg["render"].get("dark_overlay", 0.65)),
        "render_profile": str(cfg["render"].get("render_profile", "production")),
        "ffmpeg": str(ffmpeg_exe),
        "spec": asdict(spec),
    }
    write_json(slot_dir / "01_prepare.json", payload)
    return payload


@_stage_guard("render_video")
def page12_render_slot(prepared: dict[str, Any]) -> dict[str, Any]:
    request = prepared["request"]
    page_key = prepared["page_key"]
    slot_dir = Path(prepared["slot_dir"])
    spec = _spec_from_dict(prepared["spec"])
    stem = f"reel_{page_key}_{request['target_date'].replace('-', '')}_{request['slot'].replace(':', '')}_{prepared['batch_key']}"
    ass_path, mp4_path, png_path, manifest_path = render_reel(
        ffmpeg_exe=Path(prepared["ffmpeg"]),
        ass_template_path=ASS_TEMPLATE,
        run_dir=slot_dir,
        stem=stem,
        spec=spec,
        background_video=prepared["background_path"],
        dark_overlay=float(prepared["dark_overlay"]),
        render_profile=str(prepared["render_profile"]),
    )
    payload = {
        **prepared,
        "ass_path": str(ass_path),
        "video_path": str(mp4_path),
        "preview_png": str(png_path),
        "manifest_path": str(manifest_path),
    }
    write_json(slot_dir / "02_render.json", payload)
    return payload


@_stage_guard("upload_schedule")
def page12_upload_slot(rendered: dict[str, Any]) -> dict[str, Any]:
    request = rendered["request"]
    slot_dir = Path(rendered["slot_dir"])
    manifest = read_json(Path(rendered["manifest_path"]))
    caption = build_caption(manifest, PROJECT_ROOT)
    upload = run_meta_upload(
        page_key=rendered["page_key"],
        asset_id=rendered["asset_id"],
        video=Path(rendered["video_path"]),
        caption=caption,
        when_iso=request["target_iso"],
    )
    payload = {**rendered, "caption": caption, "upload": upload}
    write_json(slot_dir / "03_upload.json", payload)
    return payload


def page12_telegram_slot(uploaded: dict[str, Any]) -> dict[str, Any]:
    request = uploaded["request"]
    slot_dir = Path(uploaded["slot_dir"])
    if _is_failed_payload(uploaded):
        send_status(
            uploaded["page_key"],
            request["slot"],
            request["target_iso"],
            "failed",
            video=uploaded.get("video_path", ""),
            error=f"{uploaded.get('failed_stage', 'unknown')}: {uploaded.get('error', '')}",
            run_folder=str(slot_dir),
            failed_stage=str(uploaded.get("failed_stage", "unknown")),
        )
        payload = {**uploaded, "telegram": "sent"}
        write_json(slot_dir / "04_telegram.json", payload)
        _write_slot_complete(request, payload, "failed")
        return payload

    send_status(
        uploaded["page_key"],
        request["slot"],
        request["target_iso"],
        "scheduled",
        video=uploaded["video_path"],
        run_folder=str(slot_dir),
    )
    payload = {**uploaded, "telegram": "sent"}
    write_json(slot_dir / "04_telegram.json", payload)
    _write_slot_complete(request, payload, "complete")
    return payload


def _media_arg(path: str | Path) -> str:
    """Pass Windows paths to Windows ffmpeg when Airflow runs from WSL."""
    value = Path(path)
    return _wsl_to_windows_path(value) if os.name != "nt" else str(value)


def _resolve_config_path(path_text: str | Path) -> Path:
    text = str(path_text or "").strip()
    if re.match(r"^[A-Za-z]:[\\/]", text):
        if os.name == "nt":
            return Path(text).resolve()
        drive = text[0].lower()
        rest = text[2:].replace("\\", "/").lstrip("/")
        return Path(f"/mnt/{drive}/{rest}")
    path = Path(text)
    if path.is_absolute():
        return path.resolve()
    return (PROJECT_ROOT / path).resolve()


def _page1_concept_prompt(request: dict[str, Any]) -> str:
    seed = f"{request.get('target_date')} {request.get('slot')} {random.randint(1000, 9999)}"
    formats = [
        "female psychology facts",
        "rules for women when dating",
        "dangerous woman signs",
        "things women crave silently",
        "truths about men worth waiting for",
        "women secrets",
        "when a woman tests you",
        "men vs women psychology",
        "things she notices silently",
        "signs she is emotionally done",
    ]
    format_focus = formats[abs(hash(seed)) % len(formats)]
    return f"""
Create one original viral Facebook Reel poster concept for a page called Female Psychology.

Target audience: USA, UK, Canada, Australia adults interested in dating, attraction, relationship psychology, women psychology, boundaries, confidence, modern romance, and emotional maturity.
Format focus for this reel: {format_focus}.

Return ONLY valid JSON with this exact shape:
{{
  "topic": "short topic",
  "format_type": "female_facts|dating_rules|dangerous_woman|silent_cravings|women_secrets|testing_signs|men_vs_women|emotional_done|psychology_truths",
  "headline": "BIG ALL CAPS headline, 5-11 words",
  "points": [
    {{"label": "1", "text": "one sharp sentence", "highlight": "exact phrase from text"}},
    {{"label": "2", "text": "one sharp sentence", "highlight": "exact phrase from text"}},
    {{"label": "3", "text": "one sharp sentence", "highlight": "exact phrase from text"}},
    {{"label": "4", "text": "one sharp sentence", "highlight": "exact phrase from text"}},
    {{"label": "5", "text": "one sharp sentence", "highlight": "exact phrase from text"}},
    {{"label": "6", "text": "one sharp sentence", "highlight": "exact phrase from text"}},
    {{"label": "7", "text": "one sharp sentence", "highlight": "exact phrase from text"}}
  ],
  "question": "one easy comment question",
  "caption": "one engaging caption with a save/comment prompt",
  "hashtags": ["#DatingAdvice", "#RelationshipAdvice", "#FemalePsychology", "#ModernDating", "#SelfRespect"],
  "background_mood": "dark night path, trees, streetlamp, lonely cinematic mood"
}}

Rules:
- Do not mention Corey Wayne or any teacher/source name.
- Use safe, monetization-friendly relationship psychology.
- Make it bold, emotional, curiosity-driven, and direct.
- Use a list style like viral relationship psychology reels.
- Use 7 to 10 points. Prefer 7 or 8 if sentences are longer.
- Each point should be one clear sentence, 8-16 words.
- Each highlight must be an exact phrase copied from that same point text.
- Highlight should be 2-5 words, emotionally strong, and useful for yellow emphasis.
- Good headline patterns:
  - 7 FEMALE PSYCHOLOGY FACTS YOU SHOULD KNOW
  - 10 RULES FOR WOMEN WHEN DATING A MAN
  - 8 THINGS WOMEN CRAVE SILENTLY
  - 10 SIGNS YOU'RE A DANGEROUS WOMAN
  - WOMEN SECRETS
  - WHEN A WOMAN IS TESTING IF YOU'RE THE ONE
- Good angles: emotional safety, quiet tests, self-respect, silence, consistency, ambition, disrespect, chasing, mixed signals, calm confidence, walking away, boundaries, emotional presence.
- Avoid words like submit, possessed, claimed, body heats, forbidden heat, porn, blowjob, naked, or hardcore terms.
- Caption should encourage comments, saves, and shares.
- Hashtags should target high-RPM English dating and self-improvement audiences.
- Background mood must stay dark, moody, night, real-world, and minimal.
""".strip()


def _page1_normalize_concept(payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload.get("points")
    if not isinstance(rows, list):
        rows = []
    points: list[dict[str, str]] = []
    for idx, row in enumerate(rows[:10], start=1):
        if not isinstance(row, dict):
            continue
        label = _page5_repair_text(str(row.get("label") or idx).strip())
        text = _page5_repair_text(str(row.get("text") or "").strip())
        highlight = _page5_repair_text(str(row.get("highlight") or "").strip())
        text = re.sub(r"\s+", " ", text).strip(" .")
        highlight = re.sub(r"\s+", " ", highlight).strip(" .")
        if not text:
            continue
        # Keep the visual dense like the sample, but avoid unreadably long rows.
        words = re.findall(r"[A-Za-z0-9'?]+", text)
        if len(words) > 18:
            text = " ".join(words[:18])
        if not highlight or highlight.lower() not in text.lower():
            hwords = re.findall(r"[A-Za-z0-9'?]+", text)
            highlight = " ".join(hwords[max(0, min(2, len(hwords)-1)):max(2, min(6, len(hwords)))]) if hwords else ""
        points.append({"label": str(idx), "text": text + ".", "highlight": highlight})
    if len(points) < 7:
        raise RuntimeError(f"Page1 sample-style concept needs at least 7 points, got {len(points)}")
    hashtags = _page5_sanitize_list(payload.get("hashtags"), limit=10)
    hashtags = [tag if tag.startswith("#") else f"#{tag.lstrip('#')}" for tag in hashtags]
    headline = _page5_repair_text(str(payload.get("headline") or "").strip()).upper()
    concept = {
        "topic": _page5_repair_text(str(payload.get("topic") or "").strip())[:120],
        "format_type": _page5_repair_text(str(payload.get("format_type") or "female_facts").strip())[:80],
        "headline": headline[:140],
        "points": points[:10],
        "question": _page5_repair_text(str(payload.get("question") or "").strip())[:160],
        "caption": _page5_repair_text(str(payload.get("caption") or "").strip())[:700],
        "hashtags": hashtags[:10],
        "background_mood": _page5_repair_text(str(payload.get("background_mood") or "dark night path with trees and streetlamp").strip())[:180],
    }
    if not concept["headline"] or not concept["caption"] or not concept["hashtags"]:
        raise RuntimeError(f"Incomplete Page1 concept: {concept}")
    if not concept["question"]:
        concept["question"] = "Which one feels most true?"
    return concept


@_stage_guard("generate_relationship_concept")
def page1_generate_relationship_concept(request: dict[str, Any]) -> dict[str, Any]:
    page_key = str(request["page_key"])
    _, slot_dir, asset_id = _slot_meta(request)
    prompt = _page1_concept_prompt(request)
    raw = _page5_run_grok_text(prompt)
    concept = _page1_normalize_concept(_page5_extract_json(raw))
    item_id = int(datetime.now().strftime("%H%M%S"))
    prompt_path = slot_dir / f"page1_concept_prompt_{item_id}.txt"
    raw_path = slot_dir / f"page1_concept_raw_{item_id}.txt"
    concept_path = slot_dir / f"page1_concept_{item_id}.json"
    prompt_path.write_text(prompt, encoding="utf-8")
    raw_path.write_text(raw, encoding="utf-8")
    write_json(concept_path, concept)
    payload = {
        "request": request,
        "page_key": page_key,
        "asset_id": asset_id,
        "slot_dir": str(slot_dir),
        "item_id": item_id,
        "concept": concept,
        "concept_path": str(concept_path),
        "concept_prompt_path": str(prompt_path),
        "concept_raw_path": str(raw_path),
    }
    write_json(slot_dir / "01_generate_relationship_concept.json", payload)
    return payload


def _page1_image_prompt(concept: dict[str, Any]) -> str:
    points = "\n".join(f"{row['label']}. {row['text']} [highlight: {row['highlight']}]" for row in concept["points"])
    exact_rows = "\n".join(f"  {row['label']}. {row['text']}" for row in concept["points"])
    return f"""
Create one complete premium vertical Facebook Reel poster image in the same broad visual category as viral dark relationship psychology list reels.

CANVAS AND BACKGROUND:
- Portrait 9:16 image, 720x1280-friendly composition.
- Background mood: {concept['background_mood']}.
- Dark real-world night atmosphere: black/charcoal trees, quiet path or road, one soft streetlamp glow, subtle mist, deep vignette.
- Background must stay low contrast and behind the text. Text readability is the top priority.
- Do NOT draw Facebook/Instagram UI buttons, like icons, comment icons, search icons, phone status bar, captions bar, profile handle, music label, follow button, or app interface.
- Do NOT add watermark, page handle, logo, QR code, or footer branding. Our renderer will add the logo later.
- Keep lower-right corner naturally less busy for a circular logo overlay, but do not draw a circle or placeholder.

TYPOGRAPHY STYLE:
- Giant bold condensed uppercase headline in yellow and white.
- Use yellow/gold for the most important headline word and selected keyword highlights.
- Body text is white, clean, bold, and readable on a phone.
- Number labels are large and yellow/gold.
- Add thin subtle divider lines between rows if it improves readability.
- The design should feel like a viral screenshot-style reel poster, but without app UI chrome.

EXACT TEXT TO COPY INTO IMAGE:
HEADLINE:
{concept['headline']}

NUMBERED POINTS:
{points}

LAYOUT RULES:
- Put the headline in the top 25-32% of the canvas.
- Put the numbered list below the headline.
- Use exactly these rows and keep their order:
{exact_rows}
- Highlight the bracketed highlight phrase from each row in yellow/gold, but do not print the bracket text itself.
- Do not rewrite, shorten, translate, duplicate, or invent any text.
- No extra text beyond headline and numbered rows.
- If there are many rows, make typography compact but still readable.
- Keep a clean left margin and right margin.
- Do not overlap rows with background objects.

TEXT ACCURACY RULES:
- Text accuracy is more important than decoration.
- Every visible word must be spelled correctly.
- Do not create partial words, fake words, repeated fragments, broken typography, or random letters.
- If text becomes difficult, simplify the background and layout, not the words.

CONTENT TONE:
- Dark, emotional, direct, psychology-focused, high-retention.
- Premium but raw. Yellow/white on black. Moody night path background.
""".strip()


@_stage_guard("build_grok_image_prompt")
def page1_build_grok_image_prompt(concept_data: dict[str, Any]) -> dict[str, Any]:
    slot_dir = Path(concept_data["slot_dir"])
    prompt = _page1_image_prompt(concept_data["concept"])
    prompt_path = slot_dir / f"page1_image_prompt_{concept_data['item_id']}.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    payload = {**concept_data, "image_prompt_path": str(prompt_path)}
    write_json(slot_dir / "02_build_grok_image_prompt.json", payload)
    return payload


@_stage_guard("grok_generate_image")
def page1_grok_generate_image(prompt_data: dict[str, Any]) -> dict[str, Any]:
    slot_dir = Path(prompt_data["slot_dir"])
    output_dir = slot_dir / "grok_image"
    output_dir.mkdir(parents=True, exist_ok=True)
    run_checked(
        [
            sys.executable,
            str(PROJECT_ROOT / "pages" / "automation_tools" / "grok_image_cli" / "grok_cli_image_generate.py"),
            "--prompt-file",
            str(prompt_data["image_prompt_path"]),
            "--output-dir",
            str(output_dir),
            "--max-wait-seconds",
            "420",
        ],
        timeout=600,
    )
    done = read_json(output_dir / "grok_image.done.json")
    payload = {**prompt_data, "grok_output_dir": str(output_dir), "image_path": done["output"], "grok_done": done}
    write_json(slot_dir / "03_grok_generate_image.json", payload)
    return payload


@_stage_guard("render_video")
def page1_render_dynamic_image_reel(image_data: dict[str, Any]) -> dict[str, Any]:
    request = image_data["request"]
    slot_dir = Path(image_data["slot_dir"])
    cfg = load_page_config(PROJECT_ROOT, image_data["page_key"]).profile
    duration = int(cfg.get("video", {}).get("duration_sec", 15))
    audio_path = _resolve_audio_path(PROJECT_ROOT, dict(cfg))
    logo_path = _resolve_config_path(cfg.get("assets", {}).get("logo_path", ""))
    ffmpeg = _default_ffmpeg(PROJECT_ROOT)
    final_mp4 = slot_dir / (
        f"page1_{request['target_date'].replace('-', '')}_{request['slot'].replace(':', '')}_grok_poster_720x1280.mp4"
    )
    preview_png = final_mp4.with_suffix(".png")
    logo_scale = 116
    vf = (
        "[0:v]scale=720:1280:force_original_aspect_ratio=increase,"
        "crop=720:1280,setsar=1,format=rgba[bg];"
        f"[1:v]scale={logo_scale}:-1[lg];"
        "[bg][lg]overlay=W-w-28:H-h-28:format=auto,format=yuv420p[v]"
    )
    run_checked(
        [
            str(ffmpeg),
            "-y",
            "-loop",
            "1",
            "-t",
            str(duration),
            "-i",
            _media_arg(image_data["image_path"]),
            "-i",
            _media_arg(logo_path),
            "-stream_loop",
            "-1",
            "-i",
            _media_arg(audio_path),
            "-filter_complex",
            vf,
            "-map",
            "[v]",
            "-map",
            "2:a",
            "-t",
            str(duration),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-shortest",
            "-movflags",
            "+faststart",
            _media_arg(final_mp4),
        ],
        timeout=240,
    )
    run_checked(
        [
            str(ffmpeg),
            "-y",
            "-ss",
            "1",
            "-i",
            _media_arg(final_mp4),
            "-frames:v",
            "1",
            _media_arg(preview_png),
        ],
        timeout=60,
    )
    concept = image_data["concept"]
    caption = (str(concept["caption"]).strip() + "\n\n" + " ".join(concept["hashtags"])).strip()
    manifest = {
        "page": image_data["page_key"],
        "item_id": image_data["item_id"],
        "topic": concept["topic"],
        "headline": concept["headline"],
        "caption": caption,
        "image": image_data["image_path"],
        "audio": str(audio_path),
        "logo": str(logo_path),
        "output_mp4": str(final_mp4),
        "preview_png": str(preview_png),
        "duration_sec": duration,
        "render_style": "female_psychology_grok_poster",
        "created_at": datetime.utcnow().isoformat(),
        "run_dir": str(slot_dir),
    }
    manifest_path = slot_dir / f"page1_{image_data['item_id']}.manifest.json"
    write_json(manifest_path, manifest)
    payload = {
        **image_data,
        "video_path": str(final_mp4),
        "preview_png": str(preview_png),
        "manifest_path": str(manifest_path),
        "caption_text": caption,
    }
    write_json(slot_dir / "04_render_video.json", payload)
    return payload


@_stage_guard("upload_schedule")
def page1_upload_dynamic_slot(rendered: dict[str, Any]) -> dict[str, Any]:
    request = rendered["request"]
    slot_dir = Path(rendered["slot_dir"])
    upload = run_meta_upload(
        page_key=rendered["page_key"],
        asset_id=rendered["asset_id"],
        video=Path(rendered["video_path"]),
        caption=rendered["caption_text"],
        when_iso=request["target_iso"],
    )
    payload = {**rendered, "upload": upload}
    write_json(slot_dir / "05_upload.json", payload)
    return payload


def page1_telegram_dynamic_slot(uploaded: dict[str, Any]) -> dict[str, Any]:
    request = uploaded["request"]
    slot_dir = Path(uploaded["slot_dir"])
    if _is_failed_payload(uploaded):
        send_status(
            uploaded["page_key"],
            request["slot"],
            request["target_iso"],
            "failed",
            video=uploaded.get("video_path", ""),
            error=f"{uploaded.get('failed_stage', 'unknown')}: {uploaded.get('error', '')}",
            run_folder=str(slot_dir),
            failed_stage=str(uploaded.get("failed_stage", "unknown")),
        )
        payload = {**uploaded, "telegram": "sent"}
        write_json(slot_dir / "06_telegram.json", payload)
        _write_slot_complete(request, payload, "failed")
        return payload

    send_status(
        uploaded["page_key"],
        request["slot"],
        request["target_iso"],
        "scheduled",
        video=uploaded["video_path"],
        run_folder=str(slot_dir),
    )
    payload = {**uploaded, "telegram": "sent"}
    write_json(slot_dir / "06_telegram.json", payload)
    _write_slot_complete(request, payload, "complete")
    return payload


def _page3_dragon_package_prompt(request: dict[str, Any]) -> str:
    return f"""
Create one original, high-retention Facebook Reel package for a page about cinematic dragons.

You have full creative freedom. Do not follow a fixed story template. Invent the most visually addictive, cinematic, replayable dragon event you can imagine.

Goal:
Maximize watch time, replays, shares, comments, and saves for English-speaking audiences in top-RPM countries.

Hard video rules:
- No narration.
- No text overlay.
- Feels like part of a real cenematic movie.
- Different camera angles shots, fast or slow tracking shots.
- Generate scenes like - Volcano lair awakening, Hoard guarding stance, Castle siege flight, Eclipse sky soaring, Deep forest camouflaged, Misty mountain roost, Ocean trench emergence, Canyon river drinking, Crystal cave glow, Ancient ruin bonding, Celestial star dancing, Spellbound egg hatching, Fire breath blast, Mid-air duel clash, Gentle giant protective, Playful hatchling pounce, Lightning storm charging, Hidden waterfall bathing, Desert sand burrowing, Aurora borealis flying, Sunken shipwreck nesting, Snowy peak blending, Runestone circle resting, Shadow realm fading, Moonlit cliff howling, Lava river swimming, Emerald valley grazing, Clockwork city perched, Cosmic nebula floating, Frozen lake thawing.
- Add fight scenes if needed, example - Mid-air wing clash, Tail whip strike, Fire stream collision, Aerial dive bomb, Jaw snap crunch, Razor claw swipe, Ice blast freeze, Thunderous roar shockwave, Smoke screen ambush, Boulder toss smash, Venom spit splash, Lightning bolt discharge, Ground slam tremor, Wing shield block, Horn ram impale, Sonic boom screech, Shadow form evasion, Lava wave eruption, Ocean vortex plunge, Constriction tail wrap, Acid rain shower, Armor plate deflection, Cyclone wing buffet, Magma geyser burst, Talon grip grapple, Energy beam struggle, Shadow clone decoy, Meteor strike drop, Telekinetic rock throw, Final death roll.
- Describe briefly the cinematic amazing background.
- Final reel is approximately 20 seconds.
- It will be generated as 2 separate Grok CLI videos, about 10 seconds each.
- Scene B must directly continue Scene A.
- Grok CLI cannot see Scene A, so Scene B must repeat all important continuity details in words.
- The final joined video should feel like one continuous cinematic event, not two separate clips.

Return ONLY valid JSON:
{{
  "viral_idea": "one sentence describing the unique reel idea",
  "why_it_should_work": "one sentence explaining the retention hook",
  "continuity_bible": {{
    "dragon_identity": "exact dragon design, scale, texture, colors, injuries, unique traits",
    "world_identity": "exact location, cinematic background, environment, weather, era, atmosphere",
    "mood_and_lighting": "exact color palette, lighting, realism style",
    "camera_language": "how the camera should move and feel",
    "important_continuity_details": "details both scenes must preserve"
  }},
  "scene_a_end_state": "exact final moment of Scene A",
  "scene_a_prompt": "complete prompt for 10-second video A",
  "scene_b_prompt": "complete prompt for 10-second video B",
  "caption": "short engaging Facebook caption",
  "hashtags": ["#dragon", "#cinematic"]
}}

Scene prompt requirements:
- About 10-second duration.
- 9:16 vertical frame.
- 480p.
- No text, no logos, no narration, no on-screen UI.
- Hyper-realistic cinematic dragon visual.
- Immediate visual hook in first 1-2 seconds.
- One clear visual progression per scene.
- Exact dragon identity and exact world identity repeated in every scene.
- Premium realistic VFX.
- Include this negative prompt in both scene prompts:
{DRAGON_NEGATIVE_PROMPT}
""".strip()


def _page3_generate_package_json_with_retry(prompt: str, *, attempts: int = 3) -> tuple[dict[str, Any], str, list[str]]:
    raw_attempts: list[str] = []
    current_prompt = prompt
    last_error = ""
    for _ in range(max(1, attempts)):
        raw = _page5_run_grok_text(current_prompt)
        raw_attempts.append(raw)
        try:
            return _page5_extract_json(raw), raw, raw_attempts
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            current_prompt = f"""
Your previous response was not usable because it did not print the JSON object directly.

Previous response:
{raw[:6000]}

Return ONLY the complete valid JSON object for the dragon reel package.
Do not write explanations. Do not say a file was created. Do not include markdown, links, or ``` fences.
Start with {{ and end with }}.
Required keys: viral_idea, why_it_should_work, continuity_bible, scene_a_end_state, scene_a_prompt, scene_b_prompt, caption, hashtags.
""".strip()
    raise RuntimeError(f"Dragon package JSON retry failed after {attempts} attempts. Last error: {last_error}")


def _page3_normalize_dragon_package(payload: dict[str, Any]) -> dict[str, Any]:
    scene_a = _dragon_prompt_with_negative(str(payload.get("scene_a_prompt") or "").strip())
    scene_b = _dragon_prompt_with_negative(str(payload.get("scene_b_prompt") or "").strip())
    caption = _page5_repair_text(str(payload.get("caption") or "").strip())
    hashtags = _page5_sanitize_list(payload.get("hashtags"), limit=10)
    hashtags = [tag if tag.startswith("#") else f"#{tag.lstrip('#')}" for tag in hashtags]
    if not scene_a or not scene_b:
        raise RuntimeError("Dragon package missing scene prompts")
    if not caption:
        caption = _page5_repair_text(str(payload.get("viral_idea") or "A cinematic dragon event unfolds.").strip())
    if not hashtags:
        hashtags = ["#dragon", "#cinematic", "#dragonreel", "#fantasy", "#viralreels", "#vfx"]
    return {
        "viral_idea": _page5_repair_text(str(payload.get("viral_idea") or "").strip()),
        "why_it_should_work": _page5_repair_text(str(payload.get("why_it_should_work") or "").strip()),
        "continuity_bible": payload.get("continuity_bible") if isinstance(payload.get("continuity_bible"), dict) else {},
        "scene_a_end_state": _page5_repair_text(str(payload.get("scene_a_end_state") or "").strip()),
        "scene_a_prompt": scene_a,
        "scene_b_prompt": scene_b,
        "caption": caption,
        "hashtags": hashtags[:10],
    }


@_stage_guard("generate_dragon_package")
def page3_generate_dragon_package(request: dict[str, Any]) -> dict[str, Any]:
    page_key = str(request["page_key"])
    _, slot_dir, asset_id = _slot_meta(request)
    prompt = _page3_dragon_package_prompt(request)
    raw_payload, raw, raw_attempts = _page3_generate_package_json_with_retry(prompt)
    package = _page3_normalize_dragon_package(raw_payload)
    item_id = int(datetime.now().strftime("%H%M%S"))
    package_path = slot_dir / f"dragon_package_{item_id}.json"
    prompt_path = slot_dir / f"dragon_package_prompt_{item_id}.txt"
    raw_path = slot_dir / f"dragon_package_raw_{item_id}.txt"
    attempts_path = slot_dir / f"dragon_package_raw_attempts_{item_id}.json"
    prompt_path.write_text(prompt, encoding="utf-8")
    raw_path.write_text(raw, encoding="utf-8")
    write_json(attempts_path, {"attempt_count": len(raw_attempts), "attempts": raw_attempts})
    write_json(package_path, package)
    row = {
        "id": item_id,
        "heading": package.get("viral_idea") or f"Dragon Scene {item_id}",
        "scene_a_prompt": package["scene_a_prompt"],
        "scene_b_prompt": package["scene_b_prompt"],
        "scene_a_duration_sec": 10,
        "scene_b_duration_sec": 10,
        "target_resolution": "480p",
        "target_aspect_ratio": "9:16",
        "caption": package["caption"],
        "hashtags": " ".join(package["hashtags"]),
    }
    ffmpeg = PROJECT_ROOT / "tools" / "ffmpeg" / "ffmpeg-8.1.1-essentials_build" / "bin" / "ffmpeg.exe"
    ffprobe = PROJECT_ROOT / "tools" / "ffmpeg" / "ffmpeg-8.1.1-essentials_build" / "bin" / "ffprobe.exe"
    context = {
        "project_root": str(PROJECT_ROOT),
        "run_dir": str(slot_dir),
        "row_id": row["id"],
        "scene_a_prompt": _dragon_prompt_with_negative(row["scene_a_prompt"]),
        "scene_b_prompt": _dragon_prompt_with_negative(row["scene_b_prompt"]),
        "scene_a_duration_sec": row["scene_a_duration_sec"],
        "scene_b_duration_sec": row["scene_b_duration_sec"],
        "target_resolution": row["target_resolution"],
        "target_aspect_ratio": row["target_aspect_ratio"],
        "caption": row["caption"],
        "hashtags": row["hashtags"],
        "ffmpeg": str(ffmpeg),
        "ffprobe": str(ffprobe),
        "logo_path": str(PROJECT_ROOT / "pages" / page_key / "assets" / "logo" / "logo1.png"),
        "schedule_date": request["target_date"],
        "slot": request["slot"],
        "slot_compact": request["slot"].replace(":", ""),
    }
    ctx_path = slot_dir / "render_context.json"
    write_json(ctx_path, context)
    payload = {
        "request": request,
        "page_key": page_key,
        "asset_id": asset_id,
        "slot_dir": str(slot_dir),
        "context_path": str(ctx_path),
        "row": row,
        "package": package,
        "package_path": str(package_path),
        "package_prompt_path": str(prompt_path),
        "package_raw_path": str(raw_path),
        "package_raw_attempts_path": str(attempts_path),
        "package_attempt_count": len(raw_attempts),
    }
    write_json(slot_dir / "01_generate_dragon_package.json", payload)
    return payload


def page3_pick_content(request: dict[str, Any]) -> dict[str, Any]:
    """Compatibility shim for older imports; current DAG uses page3_generate_dragon_package."""
    return page3_generate_dragon_package(request)


DRAGON_NEGATIVE_PROMPT = (
    "Negative prompt: cartoon, anime, cute dragon, smooth skin, plastic texture, low detail, blurry, "
    "flat lighting, toy-like, childish, small dragon, simple scales, bad anatomy, extra heads, "
    "deformed wings, broken face, unrealistic teeth, low resolution, oversaturated colors, "
    "soft fantasy illustration."
)


def _dragon_prompt_with_negative(prompt: str) -> str:
    text = str(prompt or "").strip()
    if not text:
        return DRAGON_NEGATIVE_PROMPT
    if "negative prompt:" in text.lower():
        return text
    return f"{text}\n\n{DRAGON_NEGATIVE_PROMPT}"


def _run_dragon_step(script_name: str, args: list[str], done_path: Path, timeout_sec: int = 1800) -> dict[str, Any]:
    if done_path.exists():
        done_path.unlink(missing_ok=True)
    cmd = [sys.executable, str(PROJECT_ROOT / "pages" / "page3_dragon_cinema" / "scripts" / script_name), *args]
    proc = subprocess.Popen(cmd, cwd=PROJECT_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    start = time.time()
    while True:
        if done_path.exists():
            payload = read_json(done_path)
            stdout, stderr = proc.communicate(timeout=5)
            if proc.returncode != 0:
                raise RuntimeError(f"Step non-zero: {script_name}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}")
            if str(payload.get("status", "")) != "ok":
                raise RuntimeError(f"Step status not ok: {script_name} payload={payload}")
            return payload
        if proc.poll() is not None:
            stdout, stderr = proc.communicate(timeout=5)
            raise RuntimeError(f"Step exited before done artifact: {script_name}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}")
        if (time.time() - start) > timeout_sec:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, text=True)
            stdout, stderr = proc.communicate(timeout=5)
            raise RuntimeError(f"Step timeout: {script_name}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}")
        time.sleep(1.0)


@_stage_guard("scene_a_generate")
def page3_scene_a(prepared: dict[str, Any]) -> dict[str, Any]:
    slot_dir = Path(prepared["slot_dir"])
    done = slot_dir / "step_scene_a.done.json"
    payload = _run_dragon_step("dragon_step_scene_a.py", ["--context", prepared["context_path"], "--out", str(done)], done)
    result = {**prepared, "scene_a": payload, "scene_a_done": str(done)}
    write_json(slot_dir / "02_scene_a.json", result)
    return result


@_stage_guard("scene_b_generate")
def page3_scene_b(scene_a_data: dict[str, Any]) -> dict[str, Any]:
    slot_dir = Path(scene_a_data["slot_dir"])
    done = slot_dir / "step_scene_b.done.json"
    payload = _run_dragon_step(
        "dragon_step_scene_b.py",
        ["--context", scene_a_data["context_path"], "--in-a", scene_a_data["scene_a"]["output_mp4"], "--out", str(done)],
        done,
    )
    result = {**scene_a_data, "scene_b": payload, "scene_b_done": str(done)}
    write_json(slot_dir / "03_scene_b.json", result)
    return result


@_stage_guard("final_render")
def page3_final_render(scene_b_data: dict[str, Any]) -> dict[str, Any]:
    slot_dir = Path(scene_b_data["slot_dir"])
    done = slot_dir / "step_finalize.done.json"
    payload = _run_dragon_step(
        "dragon_step_finalize.py",
        [
            "--context",
            scene_b_data["context_path"],
            "--in-a",
            scene_b_data["scene_a"]["output_mp4"],
            "--in-b",
            scene_b_data["scene_b"]["output_mp4"],
            "--out",
            str(done),
        ],
        done,
        timeout_sec=900,
    )
    row = scene_b_data["row"]
    manifest = {
        "page": scene_b_data["page_key"],
        "row_id": row["id"],
        "heading": row["heading"],
        "scene_a_duration_sec": row["scene_a_duration_sec"],
        "scene_b_duration_sec": row["scene_b_duration_sec"],
        "resolution": row["target_resolution"],
        "aspect_ratio": row["target_aspect_ratio"],
        "caption": row["caption"],
        "hashtags": row["hashtags"],
        "scene_a_mp4": scene_b_data["scene_a"]["output_mp4"],
        "scene_b_mp4": scene_b_data["scene_b"]["output_mp4"],
        "scene_a_last_frame": scene_b_data["scene_b"].get("last_frame", ""),
        "final_mp4": payload["final_mp4"],
        "singlepass_attempted": True,
        "singlepass_fallback_used": False,
        "schedule_date": scene_b_data["request"]["target_date"],
        "slot": scene_b_data["request"]["slot"],
        "ffprobe": payload.get("ffprobe", {}),
    }
    manifest_path = slot_dir / f"dragon_{row['id']}.manifest.json"
    write_json(manifest_path, manifest)
    result = {**scene_b_data, "final": payload, "manifest_path": str(manifest_path), "video_path": payload["final_mp4"]}
    write_json(slot_dir / "04_final_render.json", result)
    return result


@_stage_guard("upload_schedule")
def page3_upload_slot(rendered: dict[str, Any]) -> dict[str, Any]:
    request = rendered["request"]
    slot_dir = Path(rendered["slot_dir"])
    caption = str(rendered["row"].get("caption", "")).strip()
    hashtags = str(rendered["row"].get("hashtags", "")).strip()
    merged = f"{caption}\n\n{hashtags}".strip() if (caption or hashtags) else ""
    upload = run_meta_upload(
        page_key=rendered["page_key"],
        asset_id=rendered["asset_id"],
        video=Path(rendered["video_path"]),
        caption=merged,
        when_iso=request["target_iso"],
    )
    result = {**rendered, "caption": merged, "upload": upload}
    write_json(slot_dir / "05_upload.json", result)
    return result


def page3_telegram_slot(uploaded: dict[str, Any]) -> dict[str, Any]:
    request = uploaded["request"]
    slot_dir = Path(uploaded["slot_dir"])
    if _is_failed_payload(uploaded):
        send_status(
            uploaded["page_key"],
            request["slot"],
            request["target_iso"],
            "failed",
            video=uploaded.get("video_path", ""),
            error=f"{uploaded.get('failed_stage', 'unknown')}: {uploaded.get('error', '')}",
            run_folder=str(slot_dir),
            failed_stage=str(uploaded.get("failed_stage", "unknown")),
        )
        result = {**uploaded, "telegram": "sent"}
        write_json(slot_dir / "06_telegram.json", result)
        _write_slot_complete(request, result, "failed")
        return result

    send_status(
        uploaded["page_key"],
        request["slot"],
        request["target_iso"],
        "scheduled",
        video=uploaded["video_path"],
        run_folder=str(slot_dir),
    )
    result = {**uploaded, "telegram": "sent"}
    write_json(slot_dir / "06_telegram.json", result)
    _write_slot_complete(request, result, "complete")
    return result


@_stage_guard("generate_content")
def page4_generate_content(request: dict[str, Any]) -> dict[str, Any]:
    page_key = str(request["page_key"])
    _, slot_dir, asset_id = _slot_meta(request)
    content_json = PAGE4_PREP._generate_content_json()
    item_id = int(datetime.now().strftime("%H%M%S"))
    narration_txt = slot_dir / f"narration_{item_id}.txt"
    content_json_file = slot_dir / f"content_{item_id}.json"
    narration_txt.write_text(content_json["narration_text"].strip() + "\n", encoding="utf-8")
    content_json_file.write_text(json.dumps(content_json, ensure_ascii=False, indent=2), encoding="utf-8")
    payload = {
        "request": request,
        "page_key": page_key,
        "asset_id": asset_id,
        "slot_dir": str(slot_dir),
        "item_id": item_id,
        "content_json": str(content_json_file),
        "narration_txt": str(narration_txt),
        "hook_used": content_json.get("hook_used", ""),
        "caption": content_json.get("caption_text", ""),
        "hashtags": content_json.get("hashtags", []),
    }
    write_json(slot_dir / "01_generate_content.json", payload)
    return payload


@_stage_guard("speechma_voice")
def page4_speechma_voice(content_data: dict[str, Any]) -> dict[str, Any]:
    slot_dir = Path(content_data["slot_dir"])
    voice_mp3 = slot_dir / f"voice_{content_data['item_id']}.mp3"
    voice_json = PROJECT_ROOT / "pages" / "page4_relationship" / "content" / "voice_profile.json"
    powershell = "powershell.exe" if os.name != "nt" else "powershell"
    cmd = [
        powershell,
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        _wsl_to_windows_path(PROJECT_ROOT / "pages" / "automation_tools" / "speechma" / "speechma_run.ps1")
        if os.name != "nt"
        else str(PROJECT_ROOT / "pages" / "automation_tools" / "speechma" / "speechma_run.ps1"),
        _wsl_to_windows_path(Path(content_data["narration_txt"])) if os.name != "nt" else str(Path(content_data["narration_txt"])),
        _wsl_to_windows_path(voice_json) if os.name != "nt" else str(voice_json),
        _wsl_to_windows_path(voice_mp3) if os.name != "nt" else str(voice_mp3),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, shell=False)
    if proc.returncode != 0:
        raise RuntimeError(f"speechma_run failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    voice_seconds = PAGE4_PREP._probe_audio_seconds(FFPROBE_EXE, voice_mp3)
    scene_count = max(3, min(5, int(math.ceil(max(1.0, voice_seconds) / 20.0))))
    result = {**content_data, "voice_mp3": str(voice_mp3), "voice_seconds": voice_seconds, "scene_count": scene_count}
    write_json(slot_dir / "02_speechma_voice.json", result)
    return result


@_stage_guard("grok_scene_images")
def page4_grok_scene_images(voice_data: dict[str, Any]) -> dict[str, Any]:
    slot_dir = Path(voice_data["slot_dir"])
    content = read_json(Path(voice_data["content_json"]))
    scenes_json = PAGE4_PREP._generate_scenes_json_with_grok(content["narration_text"], int(voice_data["scene_count"]))
    scene_prompt_json = slot_dir / f"scene_prompts_{voice_data['item_id']}.json"
    scene_prompt_txt = slot_dir / f"scene_prompts_{voice_data['item_id']}.txt"
    scene_prompt_json.write_text(json.dumps(scenes_json, ensure_ascii=False, indent=2), encoding="utf-8")
    scene_prompt_txt.write_text(PAGE4_PREP._scene_json_to_prompt_text(scenes_json), encoding="utf-8")
    grok_output_dir = slot_dir / "grok_outputs"
    grok_output_dir.mkdir(parents=True, exist_ok=True)
    run_checked(
        [
            sys.executable,
            str(PROJECT_ROOT / "pages" / "automation_tools" / "grok_image_cli" / "grok_cli_scene_images_generate.py"),
            "--prompt-file",
            str(scene_prompt_txt),
            "--output-dir",
            str(grok_output_dir),
        ]
    )
    result = {
        **voice_data,
        "scene_prompt_json": str(scene_prompt_json),
        "scene_prompt_txt": str(scene_prompt_txt),
        "grok_output_dir": str(grok_output_dir),
    }
    write_json(slot_dir / "03_grok_triptych_images.json", result)
    return result


@_stage_guard("render_video")
def page4_render_video(scene_data: dict[str, Any]) -> dict[str, Any]:
    slot_dir = Path(scene_data["slot_dir"])
    content = read_json(Path(scene_data["content_json"]))
    prep_manifest = {
        "page": scene_data["page_key"],
        "item_id": scene_data["item_id"],
        "content_json": scene_data["content_json"],
        "narration_txt": scene_data["narration_txt"],
        "voice_mp3": scene_data["voice_mp3"],
        "voice_seconds": scene_data["voice_seconds"],
        "scene_count": scene_data["scene_count"],
        "scene_prompt_json": scene_data["scene_prompt_json"],
        "scene_prompt_txt": scene_data["scene_prompt_txt"],
        "grok_output_dir": scene_data["grok_output_dir"],
        "caption": content.get("caption_text", ""),
        "hashtags": " ".join(content.get("hashtags", []) or []),
        "hook_used": content.get("hook_used", ""),
        "created_at": datetime.utcnow().isoformat(),
    }
    prep_manifest_path = slot_dir / f"page4_prepare_{scene_data['item_id']}.manifest.json"
    write_json(prep_manifest_path, prep_manifest)
    run_checked(
        [
            sys.executable,
            str(PROJECT_ROOT / "pages" / "page4_relationship" / "scripts" / "render_page4_singlepass.py"),
            "--manifest",
            str(prep_manifest_path),
            "--use-music",
            "--music-volume",
            "0.05",
        ]
    )
    final_mp4 = slot_dir / f"page4_{scene_data['item_id']}_final_singlepass_720x1280.mp4"
    final_manifest = {
        "page": scene_data["page_key"],
        "item_id": scene_data["item_id"],
        "output_mp4": str(final_mp4.resolve()),
        "caption": (str(content.get("caption_text", "")).strip() + "\n\n" + " ".join(content.get("hashtags", []) or [])).strip(),
        "spec": {"points": [{"source_item_id": scene_data["item_id"]}]},
        "created_at": datetime.utcnow().isoformat(),
        "run_dir": str(slot_dir),
    }
    final_manifest_path = slot_dir / f"page4_{scene_data['item_id']}.manifest.json"
    write_json(final_manifest_path, final_manifest)
    result = {**scene_data, "video_path": str(final_mp4), "manifest_path": str(final_manifest_path), "caption_text": final_manifest["caption"]}
    write_json(slot_dir / "04_render_panning_reel.json", result)
    return result


@_stage_guard("upload_schedule")
def page4_upload_slot(rendered: dict[str, Any]) -> dict[str, Any]:
    request = rendered["request"]
    slot_dir = Path(rendered["slot_dir"])
    upload = run_meta_upload(
        page_key=rendered["page_key"],
        asset_id=rendered["asset_id"],
        video=Path(rendered["video_path"]),
        caption=rendered["caption_text"],
        when_iso=request["target_iso"],
    )
    result = {**rendered, "upload": upload}
    write_json(slot_dir / "05_upload.json", result)
    return result


def page4_telegram_slot(uploaded: dict[str, Any]) -> dict[str, Any]:
    request = uploaded["request"]
    slot_dir = Path(uploaded["slot_dir"])
    if _is_failed_payload(uploaded):
        send_status(
            uploaded["page_key"],
            request["slot"],
            request["target_iso"],
            "failed",
            video=uploaded.get("video_path", ""),
            error=f"{uploaded.get('failed_stage', 'unknown')}: {uploaded.get('error', '')}",
            run_folder=str(slot_dir),
            failed_stage=str(uploaded.get("failed_stage", "unknown")),
        )
        result = {**uploaded, "telegram": "sent"}
        write_json(slot_dir / "06_telegram.json", result)
        _write_slot_complete(request, result, "failed")
        return result

    send_status(
        uploaded["page_key"],
        request["slot"],
        request["target_iso"],
        "scheduled",
        video=uploaded["video_path"],
        run_folder=str(slot_dir),
    )
    result = {**uploaded, "telegram": "sent"}
    write_json(slot_dir / "06_telegram.json", result)
    _write_slot_complete(request, result, "complete")
    return result


def _page5_grok_exe() -> Path:
    return resolve_grok_exe()


def _page5_run_grok_text(prompt: str) -> str:
    return run_grok_text(prompt)


def _page5_extract_json(text: str) -> dict[str, Any]:
    return extract_json_object(text)


def _page5_sanitize_list(values: Any, *, limit: int = 5) -> list[str]:
    return sanitize_text_list(values, limit=limit)


def _page5_repair_text(value: str) -> str:
    return normalize_text(value, collapse_spaces=True)


def _page5_normalize_concept(payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload.get("rows")
    if not isinstance(rows, list):
        rows = []
    normalized_rows: list[dict[str, str]] = []
    for row in rows[:5]:
        if not isinstance(row, dict):
            continue
        signal = _page5_repair_text(str(row.get("signal") or row.get("item") or "").strip())
        meaning = _page5_repair_text(str(row.get("meaning") or row.get("benefit") or "").strip())
        action = _page5_repair_text(str(row.get("action") or "").strip())
        icon = _page5_repair_text(str(row.get("icon") or signal).strip())
        if signal and meaning and action:
            normalized_rows.append(
                {
                    "signal": signal[:55],
                    "meaning": meaning[:65],
                    "action": action[:55],
                    "icon": icon[:45],
                }
            )
    if len(normalized_rows) < 5:
        raise RuntimeError(f"Page5 concept needs exactly 5 rows, got {len(normalized_rows)}")
    hashtags = _page5_sanitize_list(payload.get("hashtags"), limit=7)
    hashtags = [tag if tag.startswith("#") else f"#{tag.lstrip('#')}" for tag in hashtags]
    narration = _page5_repair_text(str(payload.get("narration") or "").strip())
    concept = {
        "topic": _page5_repair_text(str(payload.get("topic") or "").strip())[:120],
        "headline": _page5_repair_text(str(payload.get("headline") or "").strip())[:100],
        "rows": normalized_rows[:5],
        "question": _page5_repair_text(str(payload.get("question") or "").strip())[:140],
        "caption": _page5_repair_text(str(payload.get("caption") or "").strip())[:700],
        "narration": narration[:1200],
        "hashtags": hashtags[:7],
        "style_variant": str(payload.get("style_variant") or "white infographic").strip()[:80],
    }
    if not concept["question"]:
        concept["question"] = "Which one hits you first?"
    if not concept["topic"] or not concept["headline"] or not concept["caption"] or not concept["hashtags"] or not concept["narration"]:
        raise RuntimeError(f"Incomplete Page5 concept: {concept}")
    return concept


def _page5_concept_prompt(request: dict[str, Any]) -> str:
    categories = [
        "body warning signs normal people ignore",
        "gut habits that change bloating",
        "stress signals that feel physical",
        "sleep mistakes and nighttime body clues",
        "blood sugar habits and energy crashes",
        "hydration clues beyond thirst",
        "skin, hair, and nail body signals",
        "heart-friendly daily habits",
        "brain fog and focus habits",
        "liver and digestion load habits",
        "kidney hydration and salt signals",
        "posture and mobility warning signs",
        "morning routines that change energy",
        "after-30 health habits to stop",
        "after-40 body signals to respect",
        "foods that help specific body functions",
        "simple body checks people can do at home",
        "inflammation-style habits without diagnosis",
        "caffeine, sugar, and late-night habit effects",
        "walking, movement, and digestion signals",
    ]
    seed = f"{request.get('target_date')} {request.get('slot')} {random.randint(1000, 9999)}"
    category = categories[abs(hash(seed)) % len(categories)]
    return f"""
Create one original viral Facebook Reel concept for a page called Health Meter.

Target audience: USA, UK, Canada, Australia adults interested in wellness, food, nutrition, organs, and simple health facts.
Category focus for this reel: {category}.

Return ONLY valid JSON with this exact shape:
{{
  "topic": "short topic",
  "headline": "aggressive but safe headline under 9 words",
  "style_variant": "white medical infographic poster",
  "rows": [
    {{"signal": "short body sign, food, habit, or check", "meaning": "simple plain-English meaning", "action": "short practical action", "icon": "one clear icon idea"}},
    {{"signal": "short body sign, food, habit, or check", "meaning": "simple plain-English meaning", "action": "short practical action", "icon": "one clear icon idea"}},
    {{"signal": "short body sign, food, habit, or check", "meaning": "simple plain-English meaning", "action": "short practical action", "icon": "one clear icon idea"}},
    {{"signal": "short body sign, food, habit, or check", "meaning": "simple plain-English meaning", "action": "short practical action", "icon": "one clear icon idea"}},
    {{"signal": "short body sign, food, habit, or check", "meaning": "simple plain-English meaning", "action": "short practical action", "icon": "one clear icon idea"}}
  ],
  "question": "one short question viewers can answer easily",
  "narration": "dynamic conversational voiceover, 80 to 115 words, mentions all 5 rows clearly, plain English, not robotic, ends with the question",
  "caption": "one engaging caption with a save/comment prompt",
  "hashtags": ["#HealthTips", "#Nutrition", "#Wellness", "#HealthyLiving", "#FoodFacts"]
}}

    Rules:
    - Be more aggressive than generic health content, but do not claim cures or guaranteed medical treatment.
    - Do not make every reel deficiency-only or food-only; vary between body signs, simple habits, organ signals, sleep/stress signs, hydration clues, fitness/mobility facts, and practical food actions.
    - Strong viral formats are welcome: "Your body may be warning you if...", "Stop doing this after 30...", "If this happens at night...", "These signs are easy to ignore...", "Your body needs this when..."
    - Avoid repeating weak phrases like "may support" or "can help support" across rows.
    - Use stronger, varied, health-safe wording such as fuels, protects, steadies, sharpens, strengthens, cleans up, wakes up, calms, balances, restores, helps your body use, helps your body clear, keeps, feeds, and defends.
    - Every row should use a different action verb so the list feels fresh, direct, and premium.
- Make the image text extremely easy to understand: signal, meaning, action.
- Narration must be natural and varied each time; do not use the same sentence structure for every row.
- Do NOT say cures, reverses disease, heals kidney damage, prevents cancer, doctor secret, miracle, or replace medicine.
- Make it instantly understandable in one premium infographic image.
- Use exactly 5 rows.
- Caption should be monetization-safe and encourage save/comment.
- Hashtags should target high-RPM English wellness audiences.
""".strip()


@_stage_guard("generate_health_concept")
def page5_generate_health_concept(request: dict[str, Any]) -> dict[str, Any]:
    page_key = str(request["page_key"])
    _, slot_dir, asset_id = _slot_meta(request)
    prompt = _page5_concept_prompt(request)
    raw = _page5_run_grok_text(prompt)
    concept = _page5_normalize_concept(_page5_extract_json(raw))
    item_id = int(datetime.now().strftime("%H%M%S"))
    concept_path = slot_dir / f"page5_concept_{item_id}.json"
    prompt_path = slot_dir / f"page5_concept_prompt_{item_id}.txt"
    raw_path = slot_dir / f"page5_concept_raw_{item_id}.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    raw_path.write_text(raw, encoding="utf-8")
    write_json(concept_path, concept)
    payload = {
        "request": request,
        "page_key": page_key,
        "asset_id": asset_id,
        "slot_dir": str(slot_dir),
        "item_id": item_id,
        "concept": concept,
        "concept_path": str(concept_path),
        "concept_prompt_path": str(prompt_path),
        "concept_raw_path": str(raw_path),
    }
    write_json(slot_dir / "01_generate_health_concept.json", payload)
    return payload


def _page5_image_prompt(concept: dict[str, Any]) -> str:
    rows = "\n".join(
        f"{idx:02d}. {row['signal']} / {row['meaning']} / {row['action']} / icon: {row.get('icon', row['signal'])}"
        for idx, row in enumerate(concept["rows"], start=1)
    )
    question = str(concept.get("question") or "Which one hits you first?").strip()
    return f"""
Create a premium vertical health infographic image for a Facebook Reel background.

CANVAS AND BRAND RULES:
- Portrait 9:16 composition, premium mobile reel poster, clean and expensive-looking.
- Use a rich premium color palette while staying clean: cream/ivory base with deep teal, emerald, warm gold, coral, soft orange, aqua, and subtle berry accents.
- Make icons and key visual elements color-rich, glossy, and modern, but never cluttered or childish.
- Top band/header should feel like a premium wellness brand named THE HEALTH METER.
- Keep the lower-right corner visually uncluttered with natural background space; do not place text, icons, badges, placeholders, circles, frames, or decorative marks there.
- Do not add any extra watermark, handle, URL, brand badge, signature, footer branding, or random small text.
- No extra branding except the visible page name THE HEALTH METER in the top brand area.

TEXT AND LAYOUT RULES:
- Use one bold heading at the top, 4 to 7 words maximum.
- Body must contain exactly 5 clean horizontal row cards stacked vertically.
- Numbering must be small, clean, and subtle, like tiny 01, 02, 03, 04, 05 left-side labels.
- Each row must read like: short signal on first line, simple meaning on second line, practical action on third line.
- Each row must have one clear literal icon that matches the row.
- Add one single-line question below the body, easy for viewers to answer.
- Spell every word correctly. No duplicate numbering. No repeated rows. No nonsense text.
- Keep all text large enough to read on a phone.
- Avoid tiny paragraphs. Use short readable phrases only.

VISUAL STYLE RULES:
- Use color-rich but minimal premium illustrations or clean 3D-lite icons, not cluttered stock-photo collage.
- Add tasteful gradients, soft shadows, and vivid accent colors so the image feels premium, modern, and scroll-stopping.
- Use accurate-looking but non-scary medical/wellness icons.
- Prefer clean row-card separation over arrows. Use arrows only if they improve clarity.
- Keep enough whitespace between rows.
- The whole design should feel more premium than a basic Canva template.

CONTENT SAFETY RULES:
- Use curiosity and aggressive hook wording, but avoid disease-cure claims.
- Prefer strong, varied, health-safe verbs like fuels, protects, steadies, sharpens, strengthens, calms, balances, restores, feeds, defends, and helps your body clear.
- Avoid repeating "may support" or "can help support"; each point should use a different action phrase.
- Do not write cures, guarantees, reverses disease, miracle, or replaces medicine.
- No emergency medical advice, no diagnosis, no miracle cure language.

CONTENT TO PLACE IN THE IMAGE:
Heading: {concept['headline']}
Five row cards:
{rows}
Question line: {question}

IMPORTANT FINAL CHECK BEFORE OUTPUT:
- Exactly five points only.
- Number labels must be small.
- Keep the lower-right area simple and uncluttered for later logo placement, without drawing any placeholder shape.
- No footer branding or watermark.
- Text must be spelled correctly and fully readable.
""".strip()


def _page5_narration_text(concept: dict[str, Any]) -> str:
    narration = _page5_repair_text(str(concept.get("narration") or "").strip())
    if narration:
        return narration
    headline = _page5_repair_text(str(concept.get("headline") or "").strip())
    rows = concept.get("rows") if isinstance(concept.get("rows"), list) else []
    question = _page5_repair_text(str(concept.get("question") or "Which one hits you first?").strip())
    lines = [f"{headline}. Watch these five simple clues." if headline else "Watch these five simple health clues."]
    for row in rows[:5]:
        signal = _page5_repair_text(str(row.get("signal") or row.get("item") or "").strip())
        meaning = _page5_repair_text(str(row.get("meaning") or row.get("benefit") or "").strip())
        action = _page5_repair_text(str(row.get("action") or "").strip())
        if signal and meaning and action:
            lines.append(f"{signal}: {meaning}. {action}.")
    lines.append(question)
    return " ".join(" ".join(lines).split())


@_stage_guard("build_grok_image_prompt")
def page5_build_grok_image_prompt(concept_data: dict[str, Any]) -> dict[str, Any]:
    slot_dir = Path(concept_data["slot_dir"])
    concept = concept_data["concept"]
    prompt = _page5_image_prompt(concept)
    prompt_path = slot_dir / f"page5_image_prompt_{concept_data['item_id']}.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    narration_txt = slot_dir / f"page5_narration_{concept_data['item_id']}.txt"
    narration_txt.write_text(_page5_narration_text(concept), encoding="utf-8")
    payload = {**concept_data, "image_prompt_path": str(prompt_path), "narration_txt": str(narration_txt)}
    write_json(slot_dir / "02_build_grok_image_prompt.json", payload)
    return payload


@_stage_guard("grok_generate_image")
def page5_grok_generate_image(prompt_data: dict[str, Any]) -> dict[str, Any]:
    slot_dir = Path(prompt_data["slot_dir"])
    output_dir = slot_dir / "grok_image"
    output_dir.mkdir(parents=True, exist_ok=True)
    run_checked(
        [
            sys.executable,
            str(PROJECT_ROOT / "pages" / "automation_tools" / "grok_image_cli" / "grok_cli_image_generate.py"),
            "--prompt-file",
            str(prompt_data["image_prompt_path"]),
            "--output-dir",
            str(output_dir),
            "--max-wait-seconds",
            "420",
        ],
        timeout=600,
    )
    done = read_json(output_dir / "grok_image.done.json")
    payload = {**prompt_data, "grok_output_dir": str(output_dir), "image_path": done["output"], "grok_done": done}
    write_json(slot_dir / "03_grok_generate_image.json", payload)
    return payload


@_stage_guard("speechma_voice")
def page5_speechma_voice(image_data: dict[str, Any]) -> dict[str, Any]:
    slot_dir = Path(image_data["slot_dir"])
    voice_mp3 = slot_dir / f"page5_voice_{image_data['item_id']}.mp3"
    voice_json = slot_dir / "page5_voice_profile.json"
    write_json(voice_json, {"voice_label": "Ava", "pitch": 0, "speed": 0, "volume": 190})
    powershell = "powershell.exe" if os.name != "nt" else "powershell"
    speechma_script = PROJECT_ROOT / "pages" / "automation_tools" / "speechma" / "speechma_run.ps1"
    cmd = [
        powershell,
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        _wsl_to_windows_path(speechma_script) if os.name != "nt" else str(speechma_script),
        _wsl_to_windows_path(Path(image_data["narration_txt"])) if os.name != "nt" else str(Path(image_data["narration_txt"])),
        _wsl_to_windows_path(voice_json) if os.name != "nt" else str(voice_json),
        _wsl_to_windows_path(voice_mp3) if os.name != "nt" else str(voice_mp3),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, shell=False)
    if proc.returncode != 0:
        raise RuntimeError(f"speechma_run failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    voice_seconds = PAGE4_PREP._probe_audio_seconds(FFPROBE_EXE, voice_mp3)
    result = {**image_data, "voice_mp3": str(voice_mp3), "voice_seconds": voice_seconds, "voice_profile": str(voice_json)}
    write_json(slot_dir / "04_speechma_voice.json", result)
    return result


@_stage_guard("render_video")
def page5_render_video(voice_data: dict[str, Any]) -> dict[str, Any]:
    slot_dir = Path(voice_data["slot_dir"])
    request = voice_data["request"]
    final_mp4 = slot_dir / (
        f"page5_{request['target_date'].replace('-', '')}_{request['slot'].replace(':', '')}_final_720x1280.mp4"
    )
    ffmpeg = _default_ffmpeg(PROJECT_ROOT)
    ffprobe = FFPROBE_EXE if FFPROBE_EXE.exists() else Path(str(ffmpeg).replace("ffmpeg.exe", "ffprobe.exe"))
    music = PROJECT_ROOT / "pages" / "page5_health_meter" / "assets" / "music_reference" / "paulyudin-breaking-news-113982.mp3"
    logo = PROJECT_ROOT / "pages" / "page5_health_meter" / "assets" / "logo" / "logo1.png"
    run_checked(
        [
            sys.executable,
            str(PROJECT_ROOT / "pages" / "page5_health_meter" / "scripts" / "render_page5_image_voice.py"),
            "--image",
            str(voice_data["image_path"]),
            "--voice",
            str(voice_data["voice_mp3"]),
            "--music",
            str(music),
            "--logo",
            str(logo),
            "--output",
            str(final_mp4),
            "--ffmpeg",
            str(ffmpeg),
            "--ffprobe",
            str(ffprobe),
            "--music-volume",
            "0.10",
        ],
        timeout=300,
    )
    done = read_json(final_mp4.with_suffix(".done.json"))
    concept = voice_data["concept"]
    manifest = {
        "page": voice_data["page_key"],
        "item_id": voice_data["item_id"],
        "topic": concept["topic"],
        "headline": concept["headline"],
        "question": concept.get("question", ""),
        "caption": (concept["caption"].strip() + "\n\n" + " ".join(concept["hashtags"])).strip(),
        "image": voice_data["image_path"],
        "voice_mp3": voice_data["voice_mp3"],
        "output_mp4": str(final_mp4),
        "duration_sec": done.get("duration_sec"),
        "created_at": datetime.utcnow().isoformat(),
        "run_dir": str(slot_dir),
    }
    manifest_path = slot_dir / f"page5_{voice_data['item_id']}.manifest.json"
    write_json(manifest_path, manifest)
    payload = {
        **voice_data,
        "video_path": str(final_mp4),
        "manifest_path": str(manifest_path),
        "caption_text": manifest["caption"],
        "render_done": done,
    }
    write_json(slot_dir / "05_render_video.json", payload)
    return payload


@_stage_guard("upload_schedule")
def page5_upload_slot(validated: dict[str, Any]) -> dict[str, Any]:
    request = validated["request"]
    slot_dir = Path(validated["slot_dir"])
    upload = run_meta_upload(
        page_key=validated["page_key"],
        asset_id=validated["asset_id"],
        video=Path(validated["video_path"]),
        caption=validated["caption_text"],
        when_iso=request["target_iso"],
    )
    payload = {**validated, "upload": upload}
    write_json(slot_dir / "05_upload.json", payload)
    return payload


def page5_telegram_slot(uploaded: dict[str, Any]) -> dict[str, Any]:
    request = uploaded["request"]
    slot_dir = Path(uploaded["slot_dir"])
    if _is_failed_payload(uploaded):
        send_status(
            uploaded["page_key"],
            request["slot"],
            request["target_iso"],
            "failed",
            video=uploaded.get("video_path", ""),
            error=f"{uploaded.get('failed_stage', 'unknown')}: {uploaded.get('error', '')}",
            run_folder=str(slot_dir),
            failed_stage=str(uploaded.get("failed_stage", "unknown")),
        )
        payload = {**uploaded, "telegram": "sent"}
        write_json(slot_dir / "06_telegram.json", payload)
        _write_slot_complete(request, payload, "failed")
        return payload

    send_status(
        uploaded["page_key"],
        request["slot"],
        request["target_iso"],
        "scheduled",
        video=uploaded["video_path"],
        run_folder=str(slot_dir),
    )
    payload = {**uploaded, "telegram": "sent"}
    write_json(slot_dir / "06_telegram.json", payload)
    _write_slot_complete(request, payload, "complete")
    return payload



# ---------------------------------------------------------------------------
# Page 6: The Dark Theory
# ---------------------------------------------------------------------------

def _page6_normalize_content(payload: dict[str, Any]) -> dict[str, Any]:
    narration = _page5_repair_text(str(payload.get("narration_text") or "").strip())
    caption = _page5_repair_text(str(payload.get("caption") or "").strip())
    hashtags = _page5_sanitize_list(payload.get("hashtags"), limit=12)
    hashtags = [tag if tag.startswith("#") else f"#{tag.lstrip('#')}" for tag in hashtags]
    beats = payload.get("visual_beats")
    if not isinstance(beats, list):
        beats = []
    normalized_beats: list[dict[str, str]] = []
    for idx, beat in enumerate(beats[:6], start=1):
        if not isinstance(beat, dict):
            continue
        title = _page5_repair_text(str(beat.get("beat") or f"Scene {idx}").strip())[:120]
        prompt = _page5_repair_text(str(beat.get("prompt") or "").strip())
        if title and prompt:
            normalized_beats.append({"beat": title, "prompt": prompt})
    if len(normalized_beats) < 4:
        raise RuntimeError(f"Page6 needs at least 4 visual beats, got {len(normalized_beats)}")
    scene_count = int(payload.get("scene_count") or len(normalized_beats))
    scene_count = max(4, min(6, scene_count, len(normalized_beats)))
    if not narration or len(narration.split()) < 70:
        raise RuntimeError("Page6 narration is too short or empty")
    if not caption:
        raise RuntimeError("Page6 caption is empty")
    if not hashtags:
        hashtags = ["#DarkPsychology", "#HumanBehavior", "#MindGames", "#EmotionalIntelligence", "#TheDarkTheory"]
    return {
        "topic": _page5_repair_text(str(payload.get("topic") or "dark psychology").strip())[:140],
        "hook": _page5_repair_text(str(payload.get("hook") or "").strip())[:180],
        "narration_text": narration,
        "caption": caption,
        "hashtags": hashtags[:12],
        "scene_count": scene_count,
        "visual_beats": normalized_beats[:scene_count],
    }


def _page6_content_prompt(request: dict[str, Any]) -> str:
    seed = f"{request.get('target_date')} {request.get('slot')} {random.randint(1000, 9999)}"
    topics = [
        "fake charm and hidden control",
        "hot and cold attraction",
        "validation addiction",
        "silent emotional distance",
        "why toxic attention feels addictive",
        "mind games in modern dating",
        "obsession disguised as love",
        "emotional unavailability",
        "the psychology of being ignored",
        "power shifts after someone pulls away",
        "why mixed signals hook the brain",
        "dark confidence and emotional restraint",
    ]
    topic = topics[abs(hash(seed)) % len(topics)]
    return f"""
You are creating one premium Facebook Reel package for a page called THE DARK THEORY.

Core topic for this reel: {topic}
Audience: USA, UK, Canada, Australia adults interested in dark psychology, dating behavior, manipulation, toxic attraction, emotional intelligence, and hidden human motives.

Return ONLY valid JSON with this exact shape:
{{
  "topic": "short topic",
  "hook": "first two-second hook line",
  "narration_text": "90 to 130 words, short punchy lines, no markdown",
  "caption": "engaging caption with one comment/save prompt",
  "hashtags": ["#DarkPsychology", "#HumanBehavior"],
  "scene_count": 5,
  "visual_beats": [
    {{"beat": "short emotional beat", "prompt": "cinematic image prompt for this beat"}},
    {{"beat": "short emotional beat", "prompt": "cinematic image prompt for this beat"}},
    {{"beat": "short emotional beat", "prompt": "cinematic image prompt for this beat"}},
    {{"beat": "short emotional beat", "prompt": "cinematic image prompt for this beat"}},
    {{"beat": "short emotional beat", "prompt": "cinematic image prompt for this beat"}}
  ]
}}

NARRATION RULES:
- Start with a strong open loop hook such as: "The scariest part is...", "People don't notice this until...", "This is how control starts...", "The darker truth is...".
- Make it dark, sharp, emotionally intelligent, and safe for monetization.
- Do not mention Corey Wayne, Gottman, Esther Perel, therapy brands, or any source names.
- Use short sentences with psychological tension, but keep it understandable.
- End with a loop or CTA: "Follow The Dark Theory for more hidden truths." or a stronger equivalent.

VISUAL BEAT RULES:
- Create 4 to 6 beats that match the narration progression.
- Each prompt must describe one LANDSCAPE 16:9 cinematic still image designed for later 9:16 panning.
- Each image must be composed as a premium three-section horizontal story panel: left section, middle section, right section. Each section should show a different emotional moment from the same beat, connected by lighting, characters, props, and environment, so a slow 9:16 pan reveals a mini-story instead of one static scene.
- Make the three sections feel naturally connected, not like a comic strip with hard borders. Do not draw dividing lines, labels, numbers, boxes, or text.
- Style: dark cinematic psychological thriller, neo-noir realism, premium cyber-noir, rain, fog, smoke, reflections, glass, shadows, crimson/cyan/emerald/gold/deep purple accents.
- Use emotionally realistic adults, luxury-night interiors, city rain windows, mirrors, phone glow, empty streets, tense close-ups, silhouettes, subtle power dynamics.
- No text inside images, no captions, no watermark, no logo, no UI, no cartoon, no anime, no 3D toy look.
- Each prompt should be visually rich but not cluttered, with room for captions during render.

CAPTION/HASHTAG RULES:
- Caption should create comments, saves, and shares.
- Hashtags should target high-RPM English audiences and include dark psychology / behavior tags.
""".strip()


def _page6_generate_content_json_with_retry(prompt: str, *, attempts: int = 3) -> tuple[dict[str, Any], str, list[str]]:
    raw_attempts: list[str] = []
    current_prompt = prompt
    last_error = ""
    for attempt in range(1, max(1, attempts) + 1):
        raw = _page5_run_grok_text(current_prompt)
        raw_attempts.append(raw)
        try:
            return _page5_extract_json(raw), raw, raw_attempts
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            current_prompt = f"""
Your previous response was not usable because it did not print the JSON object directly.

Previous response:
{raw[:6000]}

Task:
Return ONLY the complete valid JSON object for the Facebook Reel package.

Hard rules:
- Do not write explanations.
- Do not say a file was created.
- Do not include markdown.
- Do not include a link.
- Do not include ``` fences.
- Start with {{ and end with }}.
- Include these keys exactly: topic, hook, narration_text, caption, hashtags, scene_count, visual_beats.
- visual_beats must be an array of objects with beat and prompt.
""".strip()
    raise RuntimeError(f"Page6 content JSON retry failed after {attempts} attempts. Last error: {last_error}")


@_stage_guard("generate_content")
def page6_generate_content(request: dict[str, Any]) -> dict[str, Any]:
    page_key = str(request["page_key"])
    _, slot_dir, asset_id = _slot_meta(request)
    prompt = _page6_content_prompt(request)
    content_payload, raw, raw_attempts = _page6_generate_content_json_with_retry(prompt)
    content = _page6_normalize_content(content_payload)
    item_id = int(datetime.now().strftime("%H%M%S"))
    content_path = slot_dir / f"page6_content_{item_id}.json"
    prompt_path = slot_dir / f"page6_content_prompt_{item_id}.txt"
    raw_path = slot_dir / f"page6_content_raw_{item_id}.txt"
    attempts_path = slot_dir / f"page6_content_raw_attempts_{item_id}.json"
    narration_txt = slot_dir / f"page6_narration_{item_id}.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    raw_path.write_text(raw, encoding="utf-8")
    write_json(attempts_path, {"attempt_count": len(raw_attempts), "attempts": raw_attempts})
    narration_txt.write_text(content["narration_text"].strip() + "\n", encoding="utf-8")
    write_json(content_path, content)
    payload = {
        "request": request,
        "page_key": page_key,
        "asset_id": asset_id,
        "slot_dir": str(slot_dir),
        "item_id": item_id,
        "content": content,
        "content_json": str(content_path),
        "content_prompt_path": str(prompt_path),
        "content_raw_path": str(raw_path),
        "content_raw_attempts_path": str(attempts_path),
        "content_attempt_count": len(raw_attempts),
        "narration_txt": str(narration_txt),
        "caption": content["caption"],
        "hashtags": content["hashtags"],
    }
    write_json(slot_dir / "01_generate_content.json", payload)
    return payload


@_stage_guard("speechma_voice")
def page6_speechma_voice(content_data: dict[str, Any]) -> dict[str, Any]:
    slot_dir = Path(content_data["slot_dir"])
    voice_mp3 = slot_dir / f"page6_voice_{content_data['item_id']}.mp3"
    voice_json = slot_dir / "page6_voice_profile.json"
    write_json(voice_json, {"voice_label": "Brian", "pitch": 0, "speed": 15, "volume": 190})
    powershell = "powershell.exe" if os.name != "nt" else "powershell"
    speechma_script = PROJECT_ROOT / "pages" / "automation_tools" / "speechma" / "speechma_run.ps1"
    cmd = [
        powershell,
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        _wsl_to_windows_path(speechma_script) if os.name != "nt" else str(speechma_script),
        _wsl_to_windows_path(Path(content_data["narration_txt"])) if os.name != "nt" else str(Path(content_data["narration_txt"])),
        _wsl_to_windows_path(voice_json) if os.name != "nt" else str(voice_json),
        _wsl_to_windows_path(voice_mp3) if os.name != "nt" else str(voice_mp3),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, shell=False)
    if proc.returncode != 0:
        raise RuntimeError(f"speechma_run failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    if not voice_mp3.exists() or voice_mp3.stat().st_size < 1000:
        raise RuntimeError(f"Speechma did not create a valid mp3: {voice_mp3}")
    voice_seconds = PAGE4_PREP._probe_audio_seconds(FFPROBE_EXE, voice_mp3)
    scene_count = max(4, min(6, int(content_data["content"].get("scene_count") or math.ceil(max(1.0, voice_seconds) / 12.0))))
    result = {**content_data, "voice_mp3": str(voice_mp3), "voice_seconds": voice_seconds, "scene_count": scene_count, "voice_profile": str(voice_json)}
    write_json(slot_dir / "02_speechma_voice.json", result)
    return result


def _page6_scene_prompt_text(content: dict[str, Any], scene_count: int) -> str:
    blocks: list[str] = []
    beats = content.get("visual_beats") if isinstance(content.get("visual_beats"), list) else []
    for idx, beat in enumerate(beats[:scene_count], start=1):
        prompt = _page5_repair_text(str((beat or {}).get("prompt") or "").strip())
        block = f"""
LANDSCAPE 16:9 cinematic still image for Scene {idx} of a dark psychology reel.
{prompt}
Compose the image as three connected horizontal story sections for later 9:16 panning: left section, middle section, right section. Each section must show a distinct emotional moment, pose, or reveal from the same psychological beat while keeping the same cinematic world continuous.
Do not use hard panel borders, comic boxes, text labels, numbers, arrows, or any visible section dividers; the three sections should blend naturally through lighting, architecture, shadows, reflections, and character continuity.
Premium neo-noir realism, dark thriller mood, rain/fog/smoke/reflections, crimson/cyan/emerald/gold/deep purple accents.
Emotionally realistic adults, expressive eyes, tense body language, shadows, phone glow, mirrors or glass reflections when useful.
No text, no captions, no watermark, no logo, no UI, no cartoon, no anime, no toy-like 3D, no distorted faces.
Keep the center-lower caption zone visually calm enough for later word-timed subtitles.
""".strip()
        blocks.append(block)
    return "\n\n".join(blocks).strip() + "\n"


@_stage_guard("grok_scene_images")
def page6_grok_scene_images(voice_data: dict[str, Any]) -> dict[str, Any]:
    slot_dir = Path(voice_data["slot_dir"])
    content = read_json(Path(voice_data["content_json"]))
    scene_count = int(voice_data.get("scene_count") or content.get("scene_count") or 5)
    scene_prompt_txt = slot_dir / f"page6_scene_prompts_{voice_data['item_id']}.txt"
    scene_prompt_json = slot_dir / f"page6_scene_prompts_{voice_data['item_id']}.json"
    scene_text = _page6_scene_prompt_text(content, scene_count)
    scene_prompt_txt.write_text(scene_text, encoding="utf-8")
    write_json(scene_prompt_json, {"scene_count": scene_count, "visual_beats": content.get("visual_beats", [])})
    grok_output_dir = slot_dir / "grok_scene_images"
    grok_output_dir.mkdir(parents=True, exist_ok=True)
    run_checked(
        [
            sys.executable,
            str(PROJECT_ROOT / "pages" / "automation_tools" / "grok_image_cli" / "grok_cli_scene_images_generate.py"),
            "--prompt-file",
            str(scene_prompt_txt),
            "--output-dir",
            str(grok_output_dir),
            "--max-scene-seconds",
            "480",
        ],
        timeout=3600,
    )
    result = {
        **voice_data,
        "scene_prompt_json": str(scene_prompt_json),
        "scene_prompt_txt": str(scene_prompt_txt),
        "grok_output_dir": str(grok_output_dir),
    }
    write_json(slot_dir / "03_grok_scene_images.json", result)
    return result


@_stage_guard("render_video")
def page6_render_video(scene_data: dict[str, Any]) -> dict[str, Any]:
    slot_dir = Path(scene_data["slot_dir"])
    content = read_json(Path(scene_data["content_json"]))
    ffmpeg = _default_ffmpeg(PROJECT_ROOT)
    ffprobe = FFPROBE_EXE if FFPROBE_EXE.exists() else Path(str(ffmpeg).replace("ffmpeg.exe", "ffprobe.exe"))
    logo = PROJECT_ROOT / "pages" / "page6_the_dark_theory" / "assets" / "logo" / "logo1.png"
    music_dir = PROJECT_ROOT / "pages" / "page6_the_dark_theory" / "assets" / "music"
    prep_manifest = {
        "page": scene_data["page_key"],
        "item_id": scene_data["item_id"],
        "content_json": scene_data["content_json"],
        "narration_txt": scene_data["narration_txt"],
        "voice_mp3": scene_data["voice_mp3"],
        "voice_seconds": scene_data["voice_seconds"],
        "scene_count": scene_data["scene_count"],
        "scene_prompt_json": scene_data["scene_prompt_json"],
        "scene_prompt_txt": scene_data["scene_prompt_txt"],
        "grok_output_dir": scene_data["grok_output_dir"],
        "caption": content.get("caption", ""),
        "hashtags": " ".join(content.get("hashtags", []) or []),
        "hook_used": content.get("hook", ""),
        "created_at": datetime.utcnow().isoformat(),
    }
    prep_manifest_path = slot_dir / f"page6_prepare_{scene_data['item_id']}.manifest.json"
    write_json(prep_manifest_path, prep_manifest)
    run_checked(
        [
            sys.executable,
            str(PROJECT_ROOT / "pages" / "page4_relationship" / "scripts" / "render_page4_singlepass.py"),
            "--manifest",
            str(prep_manifest_path),
            "--ffmpeg",
            str(ffmpeg),
            "--ffprobe",
            str(ffprobe),
            "--use-music",
            "--music-dir",
            str(music_dir),
            "--logo-path",
            str(logo),
            "--logo-opacity",
            "1.0",
            "--music-volume",
            "0.05",
        ],
        timeout=1200,
    )
    done_path = slot_dir / f"page4_render_{scene_data['item_id']}.done.json"
    done = read_json(done_path)
    rendered_video = Path(done["final_video"])
    request = scene_data["request"]
    final_mp4 = slot_dir / f"page6_{request['target_date'].replace('-', '')}_{request['slot'].replace(':', '')}_final_720x1280.mp4"
    if rendered_video.resolve() != final_mp4.resolve():
        final_mp4.write_bytes(rendered_video.read_bytes())
    caption_text = (str(content.get("caption", "")).strip() + "\n\n" + " ".join(content.get("hashtags", []) or [])).strip()
    manifest = {
        "page": scene_data["page_key"],
        "item_id": scene_data["item_id"],
        "topic": content.get("topic", ""),
        "hook": content.get("hook", ""),
        "caption": caption_text,
        "voice_mp3": scene_data["voice_mp3"],
        "output_mp4": str(final_mp4),
        "duration_sec": done.get("final_seconds"),
        "created_at": datetime.utcnow().isoformat(),
        "run_dir": str(slot_dir),
        "render_done": done,
    }
    manifest_path = slot_dir / f"page6_{scene_data['item_id']}.manifest.json"
    write_json(manifest_path, manifest)
    result = {**scene_data, "video_path": str(final_mp4), "manifest_path": str(manifest_path), "caption_text": caption_text, "render_done": done}
    write_json(slot_dir / "04_render_video.json", result)
    return result


@_stage_guard("upload_schedule")
def page6_upload_slot(rendered: dict[str, Any]) -> dict[str, Any]:
    request = rendered["request"]
    slot_dir = Path(rendered["slot_dir"])
    upload = run_meta_upload(
        page_key=rendered["page_key"],
        asset_id=rendered["asset_id"],
        video=Path(rendered["video_path"]),
        caption=rendered["caption_text"],
        when_iso=request["target_iso"],
    )
    payload = {**rendered, "upload": upload}
    write_json(slot_dir / "05_upload.json", payload)
    return payload


def page6_telegram_slot(uploaded: dict[str, Any]) -> dict[str, Any]:
    request = uploaded["request"]
    slot_dir = Path(uploaded["slot_dir"])
    if _is_failed_payload(uploaded):
        send_status(
            uploaded["page_key"],
            request["slot"],
            request["target_iso"],
            "failed",
            video=uploaded.get("video_path", ""),
            error=f"{uploaded.get('failed_stage', 'unknown')}: {uploaded.get('error', '')}",
            run_folder=str(slot_dir),
            failed_stage=str(uploaded.get("failed_stage", "unknown")),
        )
        payload = {**uploaded, "telegram": "sent"}
        write_json(slot_dir / "06_telegram.json", payload)
        _write_slot_complete(request, payload, "failed")
        return payload

    send_status(
        uploaded["page_key"],
        request["slot"],
        request["target_iso"],
        "scheduled",
        video=uploaded["video_path"],
        run_folder=str(slot_dir),
    )
    payload = {**uploaded, "telegram": "sent"}
    write_json(slot_dir / "06_telegram.json", payload)
    _write_slot_complete(request, payload, "complete")
    return payload


PAGE7_RECENT_SUBHEADINGS_PATH = PROJECT_ROOT / "pages" / "page7_psychological_facts" / "data" / "recent_subheadings.json"
PAGE7_RECENT_SUBHEADING_LIMIT = 60


def _page7_load_recent_subheadings() -> list[str]:
    if not PAGE7_RECENT_SUBHEADINGS_PATH.exists():
        return []
    try:
        payload = read_json(PAGE7_RECENT_SUBHEADINGS_PATH)
        values = payload.get("subheadings") if isinstance(payload, dict) else []
        if not isinstance(values, list):
            return []
        return [str(item).strip().upper() for item in values if str(item).strip()][-PAGE7_RECENT_SUBHEADING_LIMIT:]
    except Exception:
        return []


def _page7_save_recent_subheading(subheading: str) -> list[str]:
    recent = _page7_load_recent_subheadings()
    normalized = str(subheading or "").strip().upper()
    if normalized:
        recent.append(normalized)
    recent = recent[-PAGE7_RECENT_SUBHEADING_LIMIT:]
    write_json(PAGE7_RECENT_SUBHEADINGS_PATH, {"subheadings": recent})
    return recent


def _page7_content_prompt(request: dict[str, Any], recent_subheadings: list[str] | None = None) -> str:
    seed = f"{request.get('target_date', '')}-{request.get('slot', '')}"
    recent_subheadings = [x for x in (recent_subheadings or []) if str(x).strip()]
    recent_block = "\n".join(f"- {item}" for item in recent_subheadings[-PAGE7_RECENT_SUBHEADING_LIMIT:])
    if not recent_block:
        recent_block = "- None yet"
    return f"""
You are creating one viral short Facebook Reel text card for a page called Psychological Facts.

Return ONLY a valid JSON object. No markdown. No commentary.

Style:
- Bold psychology-fact page.
- Short, punchy, useful social psychology facts.
- Top RPM countries audience: US, Canada, UK, Australia.
- Avoid celebrity names.
- Keep wording easy to understand.
- Each point should feel shareable and comment-worthy.
- Keep subheading different from the recent subheadings listed below.

Recent subheadings to avoid:
{recent_block}

JSON schema:
{{
  "title_left": "Psychological",
  "title_highlight": "Fact",
  "subheading": "2 to 4 words, uppercase-friendly topic like EMOTIONAL CONTROL or SOCIAL CONFIDENCE",
  "points": [
    "Point 1, 10 to 17 words.",
    "Point 2, 10 to 17 words.",
    "Point 3, 10 to 17 words.",
    "Point 4, 10 to 17 words.",
    "Point 5, 10 to 17 words."
  ],
  "caption": "One engaging caption, 1 to 3 short paragraphs, asks a simple question at the end.",
  "hashtags": ["#PsychologyFacts", "#Mindset", "#SelfImprovement", "#HumanBehavior", "#EmotionalIntelligence", "#LifeAdvice", "#SuccessMindset"]
}}

Content ideas you can rotate:
- emotional control
- confidence
- discipline
- attraction psychology
- body language
- silence and self-respect
- decision making
- social status
- boundaries
- focus
- mental strength

Seed: {seed}
""".strip()


def _page7_normalize_content(payload: dict[str, Any]) -> dict[str, Any]:
    points = sanitize_text_list(payload.get("points"), limit=5)
    points = [_page5_repair_text(point).rstrip(".") + "." for point in points if point.strip()]
    if len(points) < 5:
        raise RuntimeError(f"Page 7 content requires exactly 5 points, got {len(points)}")
    hashtags = _page5_sanitize_list(payload.get("hashtags"), limit=8)
    caption = _page5_repair_text(str(payload.get("caption") or "").strip())
    if not caption:
        caption = points[0]
    return {
        "title_left": "Psychological",
        "title_highlight": "Fact",
        "subheading": _page5_repair_text(str(payload.get("subheading") or "Human Behavior").strip()).upper()[:40],
        "points": points[:5],
        "caption": caption[:700],
        "hashtags": hashtags or ["#PsychologyFacts", "#Mindset", "#SelfImprovement", "#HumanBehavior", "#LifeAdvice"],
        "footer": "@PSYCHOLOGICAL FACTS",
    }


@_stage_guard("generate_fact_content")
def page7_generate_fact_content(request: dict[str, Any]) -> dict[str, Any]:
    _, slot_dir, asset_id = _slot_meta(request)
    item_id = f"{request['target_date'].replace('-', '')}_{request['slot'].replace(':', '')}"
    recent_subheadings_before = _page7_load_recent_subheadings()
    prompt = _page7_content_prompt(request, recent_subheadings_before)
    raw = _page5_run_grok_text(prompt)
    content = _page7_normalize_content(_page5_extract_json(raw))
    recent_subheadings_after = _page7_save_recent_subheading(content["subheading"])
    content_path = slot_dir / f"page7_content_{item_id}.json"
    prompt_path = slot_dir / f"page7_content_prompt_{item_id}.txt"
    raw_path = slot_dir / f"page7_content_raw_{item_id}.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    raw_path.write_text(raw, encoding="utf-8")
    write_json(content_path, content)
    payload = {
        "request": request,
        "page_key": request["page_key"],
        "asset_id": asset_id,
        "slot_dir": str(slot_dir),
        "item_id": item_id,
        "content_json": str(content_path),
        "prompt_path": str(prompt_path),
        "raw_path": str(raw_path),
        "content": content,
        "recent_subheadings_before": recent_subheadings_before,
        "recent_subheadings_after": recent_subheadings_after,
        "recent_subheadings_path": str(PAGE7_RECENT_SUBHEADINGS_PATH),
    }
    write_json(slot_dir / "01_generate_fact_content.json", payload)
    return payload


@_stage_guard("render_video")
def page7_render_video(content_data: dict[str, Any]) -> dict[str, Any]:
    request = content_data["request"]
    slot_dir = Path(content_data["slot_dir"])
    item_id = content_data["item_id"]
    ffmpeg = _default_ffmpeg(PROJECT_ROOT)
    audio = PROJECT_ROOT / "pages" / "page7_psychological_facts" / "assets" / "music_reference" / "reference_audio.wav"
    output = slot_dir / f"page7_{request['target_date'].replace('-', '')}_{request['slot'].replace(':', '')}_final_720x1280.mp4"
    run_checked(
        [
            sys.executable,
            str(PROJECT_ROOT / "pages" / "page7_psychological_facts" / "scripts" / "render_page7_text_reel.py"),
            "--content",
            str(content_data["content_json"]),
            "--audio",
            str(audio),
            "--output",
            str(output),
            "--duration",
            "9.94",
            "--ffmpeg",
            str(ffmpeg),
        ],
        timeout=300,
    )
    content = read_json(Path(content_data["content_json"]))
    caption_text = (str(content.get("caption", "")).strip() + "\n\n" + " ".join(content.get("hashtags", []) or [])).strip()
    manifest = {
        "page": content_data["page_key"],
        "item_id": item_id,
        "subheading": content.get("subheading", ""),
        "points": content.get("points", []),
        "caption": caption_text,
        "output_mp4": str(output),
        "duration_sec": 9.94,
        "created_at": datetime.utcnow().isoformat(),
        "run_dir": str(slot_dir),
    }
    manifest_path = slot_dir / f"page7_{item_id}.manifest.json"
    write_json(manifest_path, manifest)
    payload = {**content_data, "video_path": str(output), "manifest_path": str(manifest_path), "caption_text": caption_text}
    write_json(slot_dir / "02_render_video.json", payload)
    return payload


@_stage_guard("upload_schedule")
def page7_upload_slot(rendered: dict[str, Any]) -> dict[str, Any]:
    request = rendered["request"]
    slot_dir = Path(rendered["slot_dir"])
    upload = run_meta_upload(
        page_key=rendered["page_key"],
        asset_id=rendered["asset_id"],
        video=Path(rendered["video_path"]),
        caption=rendered["caption_text"],
        when_iso=request["target_iso"],
    )
    payload = {**rendered, "upload": upload}
    write_json(slot_dir / "03_upload.json", payload)
    return payload


def page7_telegram_slot(uploaded: dict[str, Any]) -> dict[str, Any]:
    request = uploaded["request"]
    slot_dir = Path(uploaded["slot_dir"])
    if _is_failed_payload(uploaded):
        send_status(
            uploaded["page_key"],
            request["slot"],
            request["target_iso"],
            "failed",
            video=uploaded.get("video_path", ""),
            error=f"{uploaded.get('failed_stage', 'unknown')}: {uploaded.get('error', '')}",
            run_folder=str(slot_dir),
            failed_stage=str(uploaded.get("failed_stage", "unknown")),
        )
        payload = {**uploaded, "telegram": "sent"}
        write_json(slot_dir / "04_telegram.json", payload)
        _write_slot_complete(request, payload, "failed")
        return payload

    send_status(
        uploaded["page_key"],
        request["slot"],
        request["target_iso"],
        "scheduled",
        video=uploaded["video_path"],
        run_folder=str(slot_dir),
    )
    payload = {**uploaded, "telegram": "sent"}
    write_json(slot_dir / "04_telegram.json", payload)
    _write_slot_complete(request, payload, "complete")
    return payload

# ---------------------------------------------------------------------------
# Page 8: Funny Universe animated cartoon comics
# ---------------------------------------------------------------------------

PAGE8_ROOT = PROJECT_ROOT / "pages" / "page8_funny_universe"
PAGE8_CHARACTERS_PATH = PAGE8_ROOT / "data" / "characters.json"
PAGE8_ROTATION_PATH = PAGE8_ROOT / "data" / "character_rotation.json"
PAGE8_STYLE_RULES_PATH = PAGE8_ROOT / "assets" / "style" / "grok_video_style_rules.txt"
PAGE8_MUSIC_DIR = PAGE8_ROOT / "assets" / "music"
PAGE8_MUSIC_METADATA_PATH = PAGE8_MUSIC_DIR / "music_metadata.json"
PAGE8_LOGO_PATH = PAGE8_ROOT / "assets" / "logo" / "logo1.png"
PAGE8_LOGO_WIDTH = 116
PAGE8_LOGO_MARGIN_RIGHT = 28
PAGE8_LOGO_MARGIN_BOTTOM = 28


def _page8_load_characters() -> list[dict[str, Any]]:
    payload = json.loads(PAGE8_CHARACTERS_PATH.read_text(encoding="utf-8-sig"))
    characters = payload.get("characters")

    if not isinstance(characters, list) or not characters:
        raise RuntimeError(f"Page8 character lock file has no characters: {PAGE8_CHARACTERS_PATH}")

    return [c for c in characters if isinstance(c, dict) and c.get("character_name")]


def _page8_next_character() -> dict[str, Any]:
    characters = _page8_load_characters()

    state = {"next_index": 0}
    if PAGE8_ROTATION_PATH.exists():
        try:
            loaded = json.loads(PAGE8_ROTATION_PATH.read_text(encoding="utf-8-sig"))
            if isinstance(loaded, dict):
                state.update(loaded)
        except Exception:
            pass

    next_index = int(state.get("next_index") or 0) % len(characters)
    chosen = characters[next_index]

    new_state = {
        "next_index": (next_index + 1) % len(characters),
        "last_character": chosen["character_name"],
        "updated_at": datetime.utcnow().isoformat(),
    }
    write_json(PAGE8_ROTATION_PATH, new_state)

    return {**chosen, "rotation_index": next_index}


def _page8_character_speech_fields(character: dict[str, Any]) -> tuple[str, list[str]]:
    speech_dna_raw = character.get("speech_dna")
    speech_examples_raw = character.get("speech_examples")

    if isinstance(speech_dna_raw, dict):
        speech_dna = json.dumps(speech_dna_raw, ensure_ascii=False)
        speech_examples_raw = speech_dna_raw.get("speech_examples") or speech_examples_raw
    elif speech_dna_raw is None:
        speech_dna = ""
    else:
        speech_dna = str(speech_dna_raw)

    if isinstance(speech_examples_raw, list):
        speech_examples = [
            _page5_repair_text(str(item).strip())
            for item in speech_examples_raw
            if str(item).strip()
        ]
    elif speech_examples_raw:
        speech_examples = [_page5_repair_text(str(speech_examples_raw).strip())]
    else:
        speech_examples = []

    return _page5_repair_text(speech_dna.strip()), speech_examples


def _page8_load_music_metadata() -> dict[str, Any]:
    if not PAGE8_MUSIC_METADATA_PATH.exists():
        return {"version": 1, "duration_sec": 10, "usage_rules": [], "cues": []}
    payload = json.loads(PAGE8_MUSIC_METADATA_PATH.read_text(encoding="utf-8-sig"))
    cues = payload.get("cues")
    if not isinstance(cues, list):
        payload["cues"] = []
    return payload


def _page8_music_prompt_catalog() -> str:
    metadata = _page8_load_music_metadata()
    cue_rows: list[dict[str, Any]] = []
    for item in metadata.get("cues", []):
        if not isinstance(item, dict):
            continue
        file_name = str(item.get("file") or "").strip()
        if not file_name:
            continue
        cue_rows.append(
            {
                "file": file_name,
                "duration_sec": item.get("duration_sec"),
                "category": item.get("category"),
                "best_for": item.get("best_for"),
            }
        )
    return json.dumps(
        {
            "usage_rules": metadata.get("usage_rules", []),
            "available_cues": cue_rows,
        },
        ensure_ascii=False,
        indent=2,
    )


def _page8_content_prompt(request: dict[str, Any], character: dict[str, Any]) -> str:
    seed = f"{request.get('target_date')} {request.get('slot')} {random.randint(1000, 9999)}"

    speech_dna, speech_examples = _page8_character_speech_fields(character)
    music_catalog = _page8_music_prompt_catalog()

    return f"""
You are creating one 10-second animated cartoon comic for a Facebook page called FUNNY UNIVERSE.

Seed: {seed}

Locked main character for this run:
- Name: {character.get("character_name")}
- Visual identity: {character.get("fixed_visuals")}
- Personality: {character.get("personality")}
- Speech DNA: {speech_dna}
- Prompt anchor: {character.get("prompt_anchor")}
- Example lines: {", ".join(speech_examples)}

Other characters may appear, but exactly one locked character from the list is featured: {character.get("character_name")}.

Available meme music and SFX catalog:
{music_catalog}

Return ONLY valid JSON with this exact shape:
{{
  "topic": "short funny topic",
  "format_type": "dialogue_comic|visual_gag|silent_reaction|chaos_scene|fake_trailer|object_logic",
  "hook": "short first visual moment",
  "joke_setup": "one sentence",
  "why_funny": "one sentence explaining the setup and reversal",
  "comedy_scorecard": {{
    "joke_engine": "literal_misunderstanding|status_flip|object_logic|overconfident_failure|dramatic_overreaction|rule_backfire|visual_absurdity",
    "false_belief": "what the character wrongly believes",
    "reversal": "what proves them wrong",
    "visual_payoff": "the funniest final image, understandable without caption",
    "why_a_viewer_laughs": "specific laugh reason, not just cute or wholesome"
  }},
  "dialogue": [
    {{"speaker": "specific character name", "line": "optional short speech bubble", "start_sec": 1.4, "end_sec": 3.0}}
  ],
  "beat_plan": [
    {{"start_sec": 0.0, "end_sec": 2.1, "visual": "what happens on screen", "emotion": "face/body reaction", "dialogue_ref": "optional line summary or empty"}},
    {{"start_sec": 2.1, "end_sec": 6.8, "visual": "what changes", "emotion": "face/body reaction", "dialogue_ref": "optional line summary or empty"}},
    {{"start_sec": 6.8, "end_sec": 10.0, "visual": "payoff or final reaction", "emotion": "face/body reaction", "dialogue_ref": "optional line summary or empty"}}
  ],
  "music": {{
    "use_music": true,
    "reason": "why this cue timing helps the joke",
    "cues": [
      {{"file": "vine-boom.mp3", "start_sec": 7.2, "volume": 0.82, "reason": "dramatic reveal"}}
    ]
  }},
  "render_notes": [
    "specific timing or sync note for the renderer/Grok"
  ],
  "caption": "short Facebook caption with a comment prompt",
  "hashtags": ["#FunnyUniverse", "#CartoonComedy"],
  "video_prompt": "single complete Grok video prompt for a 10-second 9:16 animated cartoon scene"
}}

CONTENT RULES:
- The joke must be clean, family-friendly, instantly understandable, and funny in 2 seconds.
- Make it meme-funny, not just cute. The final 2 seconds need a clear absurd visual payoff.
- The viewer should understand the joke even if they mute the video and ignore the caption.
- Choose the best format for the idea: it can be dialogue-driven, mostly visual, or fully silent except music/SFX.
- Dialogue is optional. Use 0 to 3 speech bubbles total only when speech makes the joke funnier.
- If dialogue is used, speech bubbles must be very short: 2 to 8 words each.
- No emojis anywhere.
- No narration, no captions in the video, no text outside optional speech bubbles.
- If the locked character speaks, they must speak in their fixed voice.
- Supporting characters can be any funny cartoon person, animal, robot, alien, or object.
- Do not repeat the sample jokes from the character profile.

JOKE QUALITY RULES:
- The joke must have a clear setup and punchline reversal.
- Avoid plain compliments, obvious statements, or weak yes/no replies.
- Use one joke engine: literal misunderstanding, overconfident wrong logic, sarcastic status reversal, object logic, outsider logic, tiny wisdom, or dramatic overreaction.
- Punchline must be sharper than setup and match the locked character voice.
- Do not make the ending merely friendly, cute, proud, wholesome, or motivational.
- Do not rely only on a pun. The pun can be a garnish, but the laugh must come from the visual reversal.
- Avoid weak Page 8 patterns: grocery sale means promotion, character makes a new friend, character simply smiles after something happens, character says a catchphrase and nothing escalates.
- Prefer one of these stronger endings: the character's logic physically backfires, a tiny object becomes overdramatic, the wrong solution creates a bigger problem, a confident character is instantly exposed, or the scene ends on a ridiculous freeze-frame.
- Good Page 8 jokes feel like short meme sketches: quick setup, visible wrong assumption, sudden consequence, funny final image.
- Bad Page 8 jokes feel like gentle preschool cartoons: soft misunderstanding, tiny pun, everyone smiles, no consequence.

TIMING RULES:
- You decide what happens at which second. Do not use a fixed 0-3/3-7/7-10 template unless it truly fits.
- The beat_plan must cover 0.0 through 10.0 seconds with 2 to 5 beats.
- Dialogue bubble start/end times, if present, must match the action and should appear when the character speaks, not late.
- Music cue start_sec must match the reveal, reaction, movement, awkward silence, or punchline.
- Use 0 to 3 music cues from the catalog. Set use_music false and cues [] when music would hurt the scene.

EMOTION/EXPRESSION RULES:
- Every joke must have visible emotion progression in beat_plan.
- Give each important character a clear face/body reaction at the exact beat where it matters.
- Give {character.get("character_name")} a character-specific reaction even in silent scenes.
- The video_prompt must include exact timing from beat_plan, dialogue timing if any, and music timing notes.

VIDEO PROMPT RULES:
- Include the locked character's full visual identity.
- Describe one simple setting, supporting characters if any, optional speech bubbles, and 2D motion across 10 seconds.
- Style must be extremely simple cartoon, thick black outlines, flat colors, cute expressive faces, soft bright background, Facebook meme aesthetic.
- Mention: no watermark, no logo, no captions, no text except optional speech bubbles.
- Include exact bubble timing when dialogue exists, so the bubble appears with the speech moment.

STRICT OUTPUT RULES:
- Return the JSON inline only.
- Do not say the file was saved.
- Do not return markdown.
- Do not return status text.
""".strip()


def _page8_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        match = re.search(r"-?\d+(?:\.\d+)?", str(value or ""))
        return float(match.group(0)) if match else default


def _page8_clamp_second(value: Any, default: float = 0.0) -> float:
    return round(max(0.0, min(10.0, _page8_float(value, default))), 2)


def _page8_normalize_dialogue(payload: dict[str, Any], character: dict[str, Any]) -> list[dict[str, Any]]:
    dialogue_raw = payload.get("dialogue")
    if not isinstance(dialogue_raw, list):
        dialogue_raw = []

    dialogue: list[dict[str, Any]] = []
    for item in dialogue_raw[:3]:
        if not isinstance(item, dict):
            continue

        speaker = _page5_repair_text(str(item.get("speaker") or "").strip())[:80]
        line = _page5_repair_text(str(item.get("line") or "").strip())[:90]
        start_sec = _page8_clamp_second(item.get("start_sec"), 0.0)
        end_sec = _page8_clamp_second(item.get("end_sec"), min(10.0, start_sec + 1.8))
        if end_sec <= start_sec:
            end_sec = round(min(10.0, start_sec + 1.5), 2)

        if speaker and line:
            dialogue.append({"speaker": speaker, "line": line, "start_sec": start_sec, "end_sec": end_sec})

    bad_speakers = {"other character", "supporting character", "character"}
    if any(row["speaker"].strip().lower() in bad_speakers for row in dialogue):
        raise RuntimeError("Page8 dialogue has generic speaker name")

    if dialogue and not any(
        str(row.get("speaker", "")).lower() == str(character["character_name"]).lower()
        for row in dialogue
    ):
        raise RuntimeError(f"Page8 dialogue must include {character['character_name']} when dialogue is used")

    return dialogue


def _page8_normalize_beat_plan(payload: dict[str, Any]) -> list[dict[str, Any]]:
    beat_raw = payload.get("beat_plan")
    if not isinstance(beat_raw, list):
        beat_raw = payload.get("emotion_beats")
    if not isinstance(beat_raw, list):
        beat_raw = []

    beat_plan: list[dict[str, Any]] = []
    for index, item in enumerate(beat_raw[:5]):
        if not isinstance(item, dict):
            continue
        fallback_start = 0.0 if not beat_plan else float(beat_plan[-1]["end_sec"])
        start_sec = _page8_clamp_second(item.get("start_sec") or item.get("start") or item.get("time"), fallback_start)
        end_sec = _page8_clamp_second(item.get("end_sec") or item.get("end"), min(10.0, start_sec + 2.5))
        if end_sec <= start_sec:
            end_sec = round(min(10.0, start_sec + 1.0), 2)
        visual = _page5_repair_text(str(item.get("visual") or item.get("body") or "").strip())[:260]
        emotion = _page5_repair_text(str(item.get("emotion") or item.get("face") or "").strip())[:220]

        beat_plan.append(
            {
                "start_sec": start_sec,
                "end_sec": end_sec,
                "visual": visual or f"Cartoon action beat {index + 1}",
                "emotion": emotion or "clear expressive reaction",
                "dialogue_ref": _page5_repair_text(str(item.get("dialogue_ref") or "").strip())[:120],
            }
        )

    if len(beat_plan) < 2:
        raise RuntimeError("Page8 needs at least 2 flexible beat_plan entries")

    beat_plan[0]["start_sec"] = 0.0
    beat_plan[-1]["end_sec"] = 10.0
    for idx in range(1, len(beat_plan)):
        if beat_plan[idx]["start_sec"] < beat_plan[idx - 1]["end_sec"] - 0.15:
            beat_plan[idx]["start_sec"] = beat_plan[idx - 1]["end_sec"]
        if beat_plan[idx]["end_sec"] <= beat_plan[idx]["start_sec"]:
            beat_plan[idx]["end_sec"] = round(min(10.0, beat_plan[idx]["start_sec"] + 1.0), 2)

    return beat_plan


def _page8_normalize_music(payload: dict[str, Any]) -> dict[str, Any]:
    music_raw = payload.get("music")
    if not isinstance(music_raw, dict):
        music_raw = {}

    metadata = _page8_load_music_metadata()
    allowed = {
        str(item.get("file")): item
        for item in metadata.get("cues", [])
        if isinstance(item, dict) and item.get("file")
    }
    cues_raw = music_raw.get("cues")
    if not isinstance(cues_raw, list):
        cues_raw = []

    cues: list[dict[str, Any]] = []
    for item in cues_raw[:3]:
        if not isinstance(item, dict):
            continue
        file_name = Path(str(item.get("file") or "")).name
        if file_name not in allowed:
            continue
        start_sec = _page8_clamp_second(item.get("start_sec") or item.get("at_second"), 0.0)
        duration = _page8_float(allowed[file_name].get("duration_sec"), 1.0)
        volume = round(max(0.15, min(1.0, _page8_float(item.get("volume"), 0.8))), 2)
        if start_sec >= 10.0:
            continue
        cues.append(
            {
                "file": file_name,
                "path": str(PAGE8_MUSIC_DIR / file_name),
                "start_sec": start_sec,
                "duration_sec": round(duration, 2),
                "volume": volume,
                "category": allowed[file_name].get("category", ""),
                "reason": _page5_repair_text(str(item.get("reason") or "").strip())[:160],
            }
        )

    use_music = bool(music_raw.get("use_music")) and bool(cues)
    return {
        "use_music": use_music,
        "reason": _page5_repair_text(str(music_raw.get("reason") or "").strip())[:220],
        "cues": cues if use_music else [],
    }


def _page8_normalize_comedy_scorecard(payload: dict[str, Any]) -> dict[str, str]:
    raw = payload.get("comedy_scorecard")
    if not isinstance(raw, dict):
        raw = {}
    return {
        "joke_engine": _page5_repair_text(str(raw.get("joke_engine") or "").strip())[:80],
        "false_belief": _page5_repair_text(str(raw.get("false_belief") or "").strip())[:180],
        "reversal": _page5_repair_text(str(raw.get("reversal") or "").strip())[:220],
        "visual_payoff": _page5_repair_text(str(raw.get("visual_payoff") or "").strip())[:220],
        "why_a_viewer_laughs": _page5_repair_text(str(raw.get("why_a_viewer_laughs") or "").strip())[:220],
    }


def _page8_validate_humor(content: dict[str, Any]) -> None:
    dialogue_text = " ".join(str(row.get("line") or "") for row in content.get("dialogue", []))
    beat_text = " ".join(
        f"{row.get('visual', '')} {row.get('emotion', '')} {row.get('dialogue_ref', '')}"
        for row in content.get("beat_plan", [])
        if isinstance(row, dict)
    )
    scorecard = content.get("comedy_scorecard") if isinstance(content.get("comedy_scorecard"), dict) else {}
    joined = " ".join(
        [
            str(content.get("topic") or ""),
            str(content.get("hook") or ""),
            str(content.get("joke_setup") or ""),
            str(content.get("why_funny") or ""),
            dialogue_text,
            beat_text,
            " ".join(str(value) for value in scorecard.values()),
        ]
    ).lower()

    weak_patterns = [
        "grocery promotion",
        "moving up in the world",
        "bunch mate",
        "new buddy",
        "new friend",
        "everyone smiles",
        "smile together",
        "wholesome",
        "cute reveal",
    ]
    if any(pattern in joined for pattern in weak_patterns):
        raise RuntimeError("Page8 joke is too soft/wholesome; needs a stronger meme visual payoff")

    payoff = str(scorecard.get("visual_payoff") or "").strip()
    laugh_reason = str(scorecard.get("why_a_viewer_laughs") or "").strip()
    reversal = str(scorecard.get("reversal") or "").strip()
    if min(len(payoff), len(laugh_reason), len(reversal)) < 18:
        raise RuntimeError("Page8 comedy_scorecard must explain reversal, visual_payoff, and laugh reason")

    payoff_terms = (
        "backfire",
        "fails",
        "wrong",
        "exposed",
        "panic",
        "freeze-frame",
        "absurd",
        "ridiculous",
        "crashes",
        "collapses",
        "overreaction",
        "consequence",
        "sudden",
    )
    if not any(term in joined for term in payoff_terms):
        raise RuntimeError("Page8 joke needs a clearer absurd consequence or visual backfire")


def _page8_normalize_content(payload: dict[str, Any], character: dict[str, Any]) -> dict[str, Any]:
    dialogue = _page8_normalize_dialogue(payload, character)
    beat_plan = _page8_normalize_beat_plan(payload)
    music = _page8_normalize_music(payload)
    comedy_scorecard = _page8_normalize_comedy_scorecard(payload)

    hashtags = _page5_sanitize_list(payload.get("hashtags"), limit=8)
    hashtags = [tag if tag.startswith("#") else f"#{tag.lstrip('#')}" for tag in hashtags]

    if not hashtags:
        hashtags = ["#FunnyUniverse", "#CartoonComedy", "#FunnyReels", "#CleanComedy"]

    video_prompt = _page5_repair_text(str(payload.get("video_prompt") or "").strip())

    if len(video_prompt.split()) < 45:
        raise RuntimeError("Page8 video_prompt is too short")

    beats_text = " Flexible timing plan: " + " ".join(
        f"{b['start_sec']}-{b['end_sec']}s: {b['visual']} Emotion: {b['emotion']}."
        for b in beat_plan
    )

    if "flexible timing plan" not in video_prompt.lower() and "start_sec" not in video_prompt.lower():
        video_prompt = video_prompt.rstrip() + beats_text

    if dialogue and "speech bubble" not in video_prompt.lower():
        bubble_text = " Speech bubble timing: " + " ".join(
            f"{row['start_sec']}-{row['end_sec']}s {row['speaker']}: \"{row['line']}\"."
            for row in dialogue
        )
        video_prompt = video_prompt.rstrip() + bubble_text

    if music["cues"]:
        music_text = " Music/SFX plan for final render: " + " ".join(
            f"{cue['file']} at {cue['start_sec']}s for {cue.get('reason') or cue.get('category')}."
            for cue in music["cues"]
        )
        video_prompt = video_prompt.rstrip() + music_text

    content = {
        "character": character,
        "topic": _page5_repair_text(str(payload.get("topic") or "funny cartoon logic").strip())[:120],
        "format_type": _page5_repair_text(str(payload.get("format_type") or "visual_gag").strip())[:80],
        "hook": _page5_repair_text(str(payload.get("hook") or "").strip())[:160],
        "joke_setup": _page5_repair_text(str(payload.get("joke_setup") or "").strip())[:240],
        "why_funny": _page5_repair_text(str(payload.get("why_funny") or "").strip())[:300],
        "comedy_scorecard": comedy_scorecard,
        "dialogue": dialogue,
        "beat_plan": beat_plan,
        "music": music,
        "render_notes": _page5_sanitize_list(payload.get("render_notes"), limit=6),
        "caption": _page5_repair_text(
            str(payload.get("caption") or "Which character should appear next?").strip()
        )[:700],
        "hashtags": hashtags,
        "video_prompt": video_prompt,
    }
    _page8_validate_humor(content)
    return content


@_stage_guard("generate_comic_content")
def page8_generate_comic_content(request: dict[str, Any]) -> dict[str, Any]:
    page_key = str(request["page_key"])
    _, slot_dir, asset_id = _slot_meta(request)

    character = _page8_next_character()
    prompt = _page8_content_prompt(request, character)

    raw = _page5_run_grok_text(prompt)
    content = _page8_normalize_content(_page5_extract_json(raw), character)

    item_id = int(datetime.now().strftime("%H%M%S"))

    content_path = slot_dir / f"page8_content_{item_id}.json"
    prompt_path = slot_dir / f"page8_content_prompt_{item_id}.txt"
    raw_path = slot_dir / f"page8_content_raw_{item_id}.txt"
    scene_prompt_path = slot_dir / f"page8_video_prompt_{item_id}.txt"

    scene_prompt_path.write_text(content["video_prompt"].strip() + "\n", encoding="utf-8")
    prompt_path.write_text(prompt, encoding="utf-8")
    raw_path.write_text(raw, encoding="utf-8")
    write_json(content_path, content)

    caption_text = (content["caption"].strip() + "\n\n" + " ".join(content["hashtags"])).strip()

    payload = {
        "request": request,
        "page_key": page_key,
        "asset_id": asset_id,
        "slot_dir": str(slot_dir),
        "item_id": item_id,
        "content": content,
        "content_json": str(content_path),
        "content_prompt_path": str(prompt_path),
        "content_raw_path": str(raw_path),
        "video_prompt_txt": str(scene_prompt_path),
        "caption_text": caption_text,
    }

    write_json(slot_dir / "01_generate_comic_content.json", payload)
    return payload


@_stage_guard("grok_animated_video")
def page8_grok_animated_video(content_data: dict[str, Any]) -> dict[str, Any]:
    slot_dir = Path(content_data["slot_dir"])
    grok_output_dir = slot_dir / "grok_animated_video"
    grok_output_dir.mkdir(parents=True, exist_ok=True)

    run_checked(
        [
            sys.executable,
            str(PROJECT_ROOT / "pages" / "automation_tools" / "grok_video_cli" / "grok_cli_scene_generate.py"),
            "--prompt-file",
            str(content_data["video_prompt_txt"]),
            "--output-dir",
            str(grok_output_dir),
            "--duration-seconds",
            "10",
            "--style-rules-file",
            str(PAGE8_STYLE_RULES_PATH),
            "--grok-exe",
            str(resolve_grok_exe()),
            "--sessions-dir",
            str(resolve_grok_exe().parents[1] / "sessions"),
            "--max-scene-seconds",
            "720",
        ],
        timeout=900,
    )

    done = read_json(grok_output_dir / "grok_outputs.done.json")
    files = done.get("files") if isinstance(done.get("files"), list) else []

    if not files:
        raise RuntimeError("Page8 Grok video did not return an MP4")

    payload = {
        **content_data,
        "grok_output_dir": str(grok_output_dir),
        "grok_done": done,
        "grok_video": str(files[0]),
    }

    write_json(slot_dir / "02_grok_animated_video.json", payload)
    return payload


def _page8_video_has_audio(video_path: Path, ffprobe: Path = FFPROBE_EXE) -> bool:
    try:
        result = subprocess.run(
            [
                str(ffprobe),
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                _media_arg(video_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return "audio" in (result.stdout or "").lower()
    except Exception:
        return True


def _page8_render_video_with_music(
    ffmpeg: Path,
    source_video: Path,
    final_mp4: Path,
    music_cues: list[dict[str, Any]],
    logo_path: Path,
) -> None:
    inputs = [str(ffmpeg), "-y", "-i", _media_arg(source_video)]
    source_audio_index = 0
    if not _page8_video_has_audio(source_video):
        inputs.extend(["-f", "lavfi", "-t", "10", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"])
        source_audio_index = 1

    logo_index = 1 if source_audio_index == 0 else 2
    inputs.extend(["-i", _media_arg(logo_path)])

    cue_start_index = logo_index + 1
    for cue in music_cues:
        inputs.extend(["-i", _media_arg(cue["path"])])

    video_filter = (
        "[0:v]scale=720:1280:force_original_aspect_ratio=decrease,"
        "pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1,format=rgba[v0];"
        f"[{logo_index}:v]scale={PAGE8_LOGO_WIDTH}:-1[lg];"
        f"[v0][lg]overlay=W-w-{PAGE8_LOGO_MARGIN_RIGHT}:H-h-{PAGE8_LOGO_MARGIN_BOTTOM}:format=auto,"
        "format=yuv420p[v]"
    )
    audio_filters = [f"[{source_audio_index}:a]volume=1.0,apad=pad_dur=10[a0]"]
    mix_labels = ["[a0]"]

    for idx, cue in enumerate(music_cues, start=1):
        input_index = cue_start_index + idx - 1
        delay_ms = int(round(float(cue["start_sec"]) * 1000))
        remaining = max(0.1, 10.0 - float(cue["start_sec"]))
        volume = float(cue.get("volume") or 0.8)
        label = f"a{idx}"
        audio_filters.append(
            f"[{input_index}:a]atrim=0:{remaining:.2f},asetpts=PTS-STARTPTS,"
            f"volume={volume:.2f},adelay={delay_ms}:all=1[{label}]"
        )
        mix_labels.append(f"[{label}]")

    filter_complex = (
        video_filter
        + ";"
        + ";".join(audio_filters)
        + ";"
        + "".join(mix_labels)
        + f"amix=inputs={len(mix_labels)}:duration=first:dropout_transition=0,atrim=0:10[a]"
    )

    run_checked(
        [
            *inputs,
            "-filter_complex",
            filter_complex,
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-t",
            "10",
            "-r",
            "30",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-movflags",
            "+faststart",
            _media_arg(final_mp4),
        ],
        timeout=300,
    )


@_stage_guard("render_video")
def page8_render_video(video_data: dict[str, Any]) -> dict[str, Any]:
    slot_dir = Path(video_data["slot_dir"])
    request = video_data["request"]
    ffmpeg = _default_ffmpeg(PROJECT_ROOT)

    source_video = Path(video_data["grok_video"])
    logo_path = PAGE8_LOGO_PATH
    if not logo_path.exists():
        raise RuntimeError(f"Page8 logo not found: {logo_path}")
    final_mp4 = slot_dir / f"page8_{request['target_date'].replace('-', '')}_{request['slot'].replace(':', '')}_final_720x1280.mp4"
    content = video_data.get("content") if isinstance(video_data.get("content"), dict) else {}
    music = content.get("music") if isinstance(content.get("music"), dict) else {}
    music_cues = music.get("cues") if isinstance(music.get("cues"), list) else []

    if music_cues:
        _page8_render_video_with_music(ffmpeg, source_video, final_mp4, music_cues, logo_path)
    else:
        video_filter = (
            "[0:v]scale=720:1280:force_original_aspect_ratio=decrease,"
            "pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1,format=rgba[v0];"
            f"[1:v]scale={PAGE8_LOGO_WIDTH}:-1[lg];"
            f"[v0][lg]overlay=W-w-{PAGE8_LOGO_MARGIN_RIGHT}:H-h-{PAGE8_LOGO_MARGIN_BOTTOM}:format=auto,"
            "format=yuv420p[v]"
        )
        run_checked(
            [
                str(ffmpeg),
                "-y",
                "-i",
                _media_arg(source_video),
                "-i",
                _media_arg(logo_path),
                "-filter_complex",
                video_filter,
                "-map",
                "[v]",
                "-map",
                "0:a?",
                "-t",
                "10",
                "-r",
                "30",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-shortest",
                _media_arg(final_mp4),
            ],
            timeout=300,
        )

    if not final_mp4.exists() or final_mp4.stat().st_size < 100_000:
        raise RuntimeError(f"Page8 render failed to create a valid MP4: {final_mp4}")

    manifest = {
        "page": video_data["page_key"],
        "item_id": video_data["item_id"],
        "character": video_data["content"]["character"]["character_name"],
        "topic": video_data["content"].get("topic", ""),
        "format_type": video_data["content"].get("format_type", ""),
        "beat_plan": video_data["content"].get("beat_plan", []),
        "dialogue": video_data["content"].get("dialogue", []),
        "music": video_data["content"].get("music", {}),
        "caption": video_data["caption_text"],
        "source_video": str(source_video),
        "logo": str(logo_path),
        "output_mp4": str(final_mp4),
        "created_at": datetime.utcnow().isoformat(),
        "run_dir": str(slot_dir),
    }

    manifest_path = slot_dir / f"page8_{video_data['item_id']}.manifest.json"
    write_json(manifest_path, manifest)

    payload = {
        **video_data,
        "video_path": str(final_mp4),
        "manifest_path": str(manifest_path),
    }

    write_json(slot_dir / "03_render_video.json", payload)
    return payload


@_stage_guard("upload_schedule")
def page8_upload_slot(rendered: dict[str, Any]) -> dict[str, Any]:
    request = rendered["request"]
    slot_dir = Path(rendered["slot_dir"])

    if bool(request.get("skip_upload")):
        payload = {
            **rendered,
            "upload": {
                "skipped": True,
                "reason": "skip_upload request flag",
            },
        }
        write_json(slot_dir / "04_upload.json", payload)
        return payload

    upload = run_meta_upload(
        page_key=rendered["page_key"],
        asset_id=rendered["asset_id"],
        video=Path(rendered["video_path"]),
        caption=rendered["caption_text"],
        when_iso=request["target_iso"],
    )

    payload = {**rendered, "upload": upload}
    write_json(slot_dir / "04_upload.json", payload)
    return payload


def page8_telegram_slot(uploaded: dict[str, Any]) -> dict[str, Any]:
    request = uploaded["request"]
    slot_dir = Path(uploaded["slot_dir"])

    if _is_failed_payload(uploaded):
        send_status(
            uploaded["page_key"],
            request["slot"],
            request["target_iso"],
            "failed",
            video=uploaded.get("video_path", ""),
            error=f"{uploaded.get('failed_stage', 'unknown')}: {uploaded.get('error', '')}",
            run_folder=str(slot_dir),
            failed_stage=str(uploaded.get("failed_stage", "unknown")),
        )

        payload = {**uploaded, "telegram": "sent"}
        write_json(slot_dir / "05_telegram.json", payload)
        _write_slot_complete(request, payload, "failed")
        return payload

    send_status(
        uploaded["page_key"],
        request["slot"],
        request["target_iso"],
        "scheduled",
        video=uploaded["video_path"],
        run_folder=str(slot_dir),
    )

    payload = {**uploaded, "telegram": "sent"}
    write_json(slot_dir / "05_telegram.json", payload)
    _write_slot_complete(request, payload, "complete")
    return payload
