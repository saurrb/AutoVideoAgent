from __future__ import annotations

import json
import math
import os
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
from autovideo.services.state_store import connect  # noqa: E402
from autovideo.services.video_renderer import render_reel  # noqa: E402

CREATE_AND_POST = load_module("airflow_create_and_post_reel", PROJECT_ROOT / "scripts" / "create_and_post_reel.py")
PAGE4_PREP = load_module(
    "airflow_page4_prepare", PROJECT_ROOT / "pages" / "page4_relationship" / "prepare_page4_narration_and_scenes.py"
)
DRAGON_CHAIN = load_module("airflow_generate_dragon_chain_reel", PROJECT_ROOT / "scripts" / "generate_dragon_chain_reel.py")

FFPROBE_EXE = PROJECT_ROOT / "tools" / "ffmpeg" / "ffmpeg-8.1.1-essentials_build" / "bin" / "ffprobe.exe"
ASS_TEMPLATE = PROJECT_ROOT / "scripts" / "reel_template.ass"


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


def _failed_payload(source: dict[str, Any], stage: str, exc: BaseException) -> dict[str, Any]:
    request = _request_from_payload(source)
    slot_dir = _slot_dir_from_payload(source, request)
    page_key = str(source.get("page_key") or request.get("page_key") or "unknown")
    error = f"{type(exc).__name__}: {exc}"
    payload = {
        **source,
        "request": request,
        "page_key": page_key,
        "slot_dir": str(slot_dir),
        "failed": True,
        "failed_stage": stage,
        "error": error,
        "traceback": traceback.format_exc(),
    }
    write_json(slot_dir / f"failed_{stage}.json", payload)
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
    caption = CREATE_AND_POST.build_caption(manifest, PROJECT_ROOT)
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


@_stage_guard("pick_content")
def page3_pick_content(request: dict[str, Any]) -> dict[str, Any]:
    page_key = str(request["page_key"])
    _, slot_dir, asset_id = _slot_meta(request)
    conn = connect(PROJECT_ROOT / "data" / "v2" / "state.sqlite3")
    row = DRAGON_CHAIN._pick_next_row_db(conn, page_key)
    ffmpeg = PROJECT_ROOT / "tools" / "ffmpeg" / "ffmpeg-8.1.1-essentials_build" / "bin" / "ffmpeg.exe"
    ffprobe = PROJECT_ROOT / "tools" / "ffmpeg" / "ffmpeg-8.1.1-essentials_build" / "bin" / "ffprobe.exe"
    context = {
        "project_root": str(PROJECT_ROOT),
        "run_dir": str(slot_dir),
        "row_id": row["id"],
        "scene_a_prompt": row["scene_a_prompt"],
        "scene_b_prompt": row["scene_b_prompt"],
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
    }
    write_json(slot_dir / "01_pick_content.json", payload)
    return payload


def _run_dragon_step(script_name: str, args: list[str], done_path: Path, timeout_sec: int = 1800) -> dict[str, Any]:
    if done_path.exists():
        done_path.unlink(missing_ok=True)
    cmd = [sys.executable, str(PROJECT_ROOT / "scripts" / script_name), *args]
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
    scene_count = max(1, int(math.ceil(max(1.0, voice_seconds) / 6.0)))
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
    write_json(slot_dir / "03_grok_scene_images.json", result)
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
    write_json(slot_dir / "04_render_video.json", result)
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
