from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
import textwrap
from datetime import timedelta
from pathlib import Path


def _run(cmd: list[str]) -> None:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"Command failed:\n{' '.join(cmd)}\nSTDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}")

def _run_capture(cmd: list[str]) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"Command failed:\n{' '.join(cmd)}\nSTDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}")
    return (p.stdout or "").strip()


def _probe_seconds(ffprobe: Path, media: Path) -> float:
    p = subprocess.run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(media),
        ],
        capture_output=True,
        text=True,
    )
    if p.returncode != 0:
        return 0.0
    try:
        return float((p.stdout or "0").strip())
    except Exception:
        return 0.0


def _ass_time_from_seconds(seconds: float | int) -> str:
    total_cs = max(0, int(round(float(seconds) * 100)))
    hh = total_cs // 360000
    rem = total_cs % 360000
    mm = rem // 6000
    rem = rem % 6000
    ss = rem // 100
    cs = rem % 100
    return f"{hh}:{mm:02d}:{ss:02d}.{cs:02d}"


def _ass_escape(s: str) -> str:
    return str(s or "").replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")


def _build_logicloom_ass(narration_text: str, duration_seconds: float, out_ass: Path) -> None:
    words = re.findall(r"\S+", str(narration_text or "").upper())
    if not words:
        words = ["..."]
    # Relationship page style reference: short chunks with active-word pulse.
    chunk_size = 3
    chunks = [words[i : i + chunk_size] for i in range(0, len(words), chunk_size)]
    total_chunks = max(1, len(chunks))
    chunk_dur = max(0.14, float(duration_seconds) / total_chunks)

    header = """[Script Info]
Title: Page4 Caption Overlay
ScriptType: v4.00+
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Base,Impact,84,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,8.0,2.2,2,58,58,480,1
Style: Active,Impact,84,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,8.0,2.2,2,58,58,480,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    t = 0.0
    for chunk in chunks:
        t0 = t
        t1 = min(duration_seconds, t0 + chunk_dur)
        plain = " ".join(_ass_escape(w) for w in chunk)
        lines.append(f"Dialogue: 0,{_ass_time_from_seconds(t0)},{_ass_time_from_seconds(t1)},Base,,0,0,480,,{plain}")
        per = max(0.08, (t1 - t0) / max(1, len(chunk)))
        for i, w in enumerate(chunk):
            ws = t0 + i * per
            we = min(t1, ws + per)
            rendered: list[str] = []
            for j, ww in enumerate(chunk):
                ew = _ass_escape(ww)
                if i == j:
                    rendered.append(r"{\1c&H0000FF92&\3c&H00000000&\bord8\shad2\b1}" + ew + r"{\rBase}")
                else:
                    rendered.append(ew)
            lines.append(
                f"Dialogue: 1,{_ass_time_from_seconds(ws)},{_ass_time_from_seconds(we)},Active,,0,0,480,,{' '.join(rendered)}"
            )
        t = t1
    ass = "\n".join(lines) + "\n"
    out_ass.write_text(ass, encoding="utf-8")


def _build_oldproject_wordtimed_ass(
    voice_mp3: Path,
    out_ass: Path,
    run_dir: Path,
    narration_text: str,
    voice_seconds: float,
) -> bool:
    """Run old project's exact multi-stage caption pipeline."""
    old_root = Path(r"C:\Users\Saurabh\Downloads\videoAgent")
    s_extract = old_root / "scripts" / "extract_word_timestamps.py"
    s_srt = old_root / "scripts" / "build_srt_from_words.py"
    s_ass = old_root / "scripts" / "build_wordtimed_ass.py"
    if not (s_extract.exists() and s_srt.exists() and s_ass.exists()):
        return False

    words = run_dir / "word_timestamps.json"
    srt = run_dir / "captions.srt"
    py = str(Path("python"))
    _run([py, str(s_extract), "--audio", str(voice_mp3), "--out", str(words)])
    _run([py, str(s_srt), "--words", str(words), "--out", str(srt)])

    _run([ py, str(s_ass), "--srt", str(srt), "--words", str(words), "--out", str(out_ass), "--preset", "logicloom_ref" ])
    return out_ass.exists()


def _wait_for_grok_event(grok_output_dir: Path, expected_count: int, max_wait_seconds: int) -> list[Path]:
    deadline = time.time() + max_wait_seconds
    event_path = grok_output_dir / "grok_outputs.done.json"

    while time.time() < deadline:
        if event_path.exists():
            payload = json.loads(event_path.read_text(encoding="utf-8-sig"))
            files = [Path(x) for x in payload.get("files", [])]
            if len(files) >= expected_count and all(x.exists() for x in files[:expected_count]):
                return files[:expected_count]
        time.sleep(1)

    # fallback scan in case event file was skipped but files exist
    vids = sorted(
        [p for p in grok_output_dir.glob("*") if p.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm"}],
        key=lambda x: x.stat().st_mtime,
    )
    if len(vids) >= expected_count:
        return vids[:expected_count]
    raise RuntimeError(
        f"Grok outputs not ready. expected={expected_count}, found={len(vids)}, dir={grok_output_dir}"
    )


def _image_to_scene_clip(ffmpeg: Path, img: Path, out_mp4: Path, sec: float = 6.0) -> None:
    fps = 30
    frames = int(sec * fps)
    vf = (
        "scale=720:1280:force_original_aspect_ratio=increase,"
        "crop=720:1280,"
        f"zoompan=z='min(1.12,zoom+0.0008)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=720x1280:fps={fps},"
        "format=yuv420p"
    )
    _run(
        [
            str(ffmpeg),
            "-y",
            "-loop",
            "1",
            "-i",
            str(img),
            "-t",
            f"{sec}",
            "-vf",
            vf,
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            str(out_mp4),
        ]
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Page4 single-pass render with event-driven scene readiness")
    ap.add_argument("--manifest", required=True, help="page4_prepare_*.manifest.json")
    ap.add_argument("--max-wait-seconds", type=int, default=1800)
    ap.add_argument(
        "--ffmpeg",
        default=r"C:\Users\Saurabh\Documents\AutoVideoAgent\tools\ffmpeg\ffmpeg-8.1.1-essentials_build\bin\ffmpeg.exe",
    )
    ap.add_argument(
        "--ffprobe",
        default=r"C:\Users\Saurabh\Documents\AutoVideoAgent\tools\ffmpeg\ffmpeg-8.1.1-essentials_build\bin\ffprobe.exe",
    )
    ap.add_argument("--use-music", action="store_true", help="Enable background music mix. Default is narration-only.")
    ap.add_argument(
        "--music-dir",
        default=r"C:\Users\Saurabh\Documents\AutoVideoAgent\pages\page4_relationship\assets\music",
    )
    ap.add_argument(
        "--logo-path",
        default=r"C:\Users\Saurabh\Downloads\cropped_circle_image.png",
    )
    ap.add_argument("--logo-x-ratio", type=float, default=0.8213461538)
    ap.add_argument("--logo-y-ratio", type=float, default=0.8962765957)
    ap.add_argument("--logo-w-ratio", type=float, default=0.0883413462)
    ap.add_argument("--logo-opacity", type=float, default=1.0)
    ap.add_argument("--keep-intermediates", action="store_true", help="Keep intermediate artifacts for debugging.")
    args = ap.parse_args()

    manifest_path = Path(args.manifest).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    run_dir = manifest_path.parent
    ffmpeg = Path(args.ffmpeg)
    ffprobe = Path(args.ffprobe)
    voice_mp3 = Path(manifest["voice_mp3"])
    grok_output_dir = Path(manifest["grok_output_dir"])
    expected_count = int(manifest.get("scene_count", 1))
    narration_text = Path(manifest.get("narration_txt", "")).read_text(encoding="utf-8-sig").strip() if manifest.get("narration_txt") else ""

    scenes = _wait_for_grok_event(grok_output_dir, expected_count, args.max_wait_seconds)
    scene_video_inputs: list[Path] = []
    for idx, s in enumerate(scenes, start=1):
        if s.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            clip = run_dir / f"scene_imgclip_{idx:02d}.mp4"
            _image_to_scene_clip(ffmpeg, s, clip, sec=6.0)
            scene_video_inputs.append(clip)
        else:
            scene_video_inputs.append(s)

    concat_list = run_dir / "scene_concat_list.txt"
    concat_lines: list[str] = []
    for p in scene_video_inputs:
        safe = str(p).replace("'", "''")
        concat_lines.append(f"file '{safe}'\n")
    concat_list.write_text("".join(concat_lines), encoding="utf-8")

    concat_video = run_dir / f"page4_concat_{manifest['item_id']}.mp4"
    _run(
        [
            str(ffmpeg),
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-an",
            "-vf",
            "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,fps=30,format=yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            str(concat_video),
        ]
    )

    music_files = sorted([p for p in Path(args.music_dir).glob("*") if p.suffix.lower() in {".mp3", ".m4a", ".wav", ".aac"}])
    bg_music = music_files[0] if (args.use_music and music_files) else None

    final_video = run_dir / f"page4_{manifest['item_id']}_final_singlepass_720x1280.mp4"
    if bg_music and bg_music.exists():
        _run(
            [
                str(ffmpeg),
                "-y",
                "-stream_loop",
                "-1",
                "-i",
                str(bg_music),
                "-i",
                str(voice_mp3),
                "-filter_complex",
                "[0:a]volume=0.12[a0];[1:a]volume=1.0[a1];[a0][a1]amix=inputs=2:duration=longest:dropout_transition=2[aout]",
                "-map",
                "[aout]",
                "-vn",
                "-shortest",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                str(run_dir / "page4_audio_mix.aac"),
            ]
        )
        mixed_audio = run_dir / "page4_audio_mix.aac"
    else:
        mixed_audio = voice_mp3

    # Retiming: make scene motion fit narration duration (audio remains untouched).
    concat_seconds = _probe_seconds(ffprobe, concat_video)
    voice_seconds = _probe_seconds(ffprobe, voice_mp3)
    timing_video = concat_video
    if concat_seconds > 0.01 and voice_seconds > 0.01:
        speed_ratio = voice_seconds / concat_seconds
        if abs(speed_ratio - 1.0) > 0.005:
            retimed_video = run_dir / f"page4_concat_{manifest['item_id']}_retimed.mp4"
            _run(
                [
                    str(ffmpeg),
                    "-y",
                    "-i",
                    str(concat_video),
                    "-an",
                    "-vf",
                    f"setpts={speed_ratio:.8f}*PTS,fps=30,format=yuv420p",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "20",
                    str(retimed_video),
                ]
            )
            timing_video = retimed_video

    caption_ass = run_dir / f"page4_caption_{manifest['item_id']}.ass"
    if not _build_oldproject_wordtimed_ass(voice_mp3, caption_ass, run_dir, narration_text, voice_seconds):
        _build_logicloom_ass(narration_text, voice_seconds, caption_ass)
    ass_ff = str(caption_ass).replace("\\", "/").replace(":", r"\:")
    logo_path = Path(args.logo_path)
    if (not logo_path.exists()) and str(logo_path).lower().endswith(r"\downloads\videoagent\assets\branding\logos\logo1.png"):
        fallback_logo = Path(r"C:\Users\Saurabh\Documents\AutoVideoAgent\pages\page4_relationship\assets\logo\logo1.png")
        if fallback_logo.exists():
            logo_path = fallback_logo
    use_logo = logo_path.exists()
    logo_opacity = max(0.0, min(1.0, float(args.logo_opacity)))

    if use_logo:
        logo_w_expr = f"iw*{float(args.logo_w_ratio):.10f}"
        logo_x_expr = f"W*{float(args.logo_x_ratio):.10f}"
        logo_y_expr = f"H*{float(args.logo_y_ratio):.10f}"
        filter_chain = (
            f"[1:v]scale={logo_w_expr}:-1,format=rgba,colorchannelmixer=aa={logo_opacity}[lg];"
            f"[0:v]subtitles='{ass_ff}'[vc];"
            f"[vc][lg]overlay=x={logo_x_expr}:y={logo_y_expr}:format=auto[vout]"
        )
        map_video = "[vout]"
    else:
        filter_chain = f"[0:v]subtitles='{ass_ff}'[vout]"
        map_video = "[vout]"

    _run(
        [
            str(ffmpeg),
            "-y",
            "-i",
            str(timing_video),
            *(["-i", str(logo_path)] if use_logo else []),
            "-i",
            str(mixed_audio),
            "-filter_complex",
            filter_chain,
            "-map",
            map_video,
            "-map",
            f"{1 if not use_logo else 2}:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            str(final_video),
        ]
    )

    payload = {
        "status": "ok",
        "manifest": str(manifest_path),
        "scene_count_expected": expected_count,
        "scene_count_used": len(scenes),
        "scene_files": [str(x) for x in scenes],
        "scene_video_inputs": [str(x) for x in scene_video_inputs],
        "voice_mp3": str(voice_mp3),
        "concat_video": str(concat_video),
        "final_video": str(final_video),
        "final_seconds": _probe_seconds(ffprobe, final_video),
    }
    done_path = run_dir / f"page4_render_{manifest['item_id']}.done.json"
    done_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.keep_intermediates:
        scene_prompt_json_s = str(manifest.get("scene_prompt_json", "") or "").strip()
        scene_prompt_txt_s = str(manifest.get("scene_prompt_txt", "") or "").strip()
        scene_prompt_json = Path(scene_prompt_json_s) if scene_prompt_json_s else None
        scene_prompt_txt = Path(scene_prompt_txt_s) if scene_prompt_txt_s else None
        cleanup_files = [
            run_dir / "scene_concat_list.txt",
            run_dir / "word_timestamps.json",
            run_dir / "captions.srt",
            caption_ass,
            concat_video,
            run_dir / f"page4_concat_{manifest['item_id']}_retimed.mp4",
            run_dir / f"page4_audio_mix.aac",
            scene_prompt_json,
            scene_prompt_txt,
        ]
        cleanup_globs = ["scene_imgclip_*.mp4"]
        for f in cleanup_files:
            if f and f.exists() and f.is_file():
                try:
                    f.unlink()
                except Exception:
                    pass
        for pat in cleanup_globs:
            for f in run_dir.glob(pat):
                try:
                    f.unlink()
                except Exception:
                    pass

    print(f"MANIFEST={manifest_path}")
    print(f"SCENES={len(scenes)}")
    print(f"FINAL_VIDEO={final_video}")
    print(f"RENDER_DONE={done_path}")


if __name__ == "__main__":
    main()
