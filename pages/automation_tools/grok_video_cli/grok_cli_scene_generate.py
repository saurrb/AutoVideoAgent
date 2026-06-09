from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def _default_windows_home() -> Path | None:
    candidates = [
        Path("/mnt/c/Users/Saurabh"),
        Path(r"C:\Users\Saurabh"),
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _default_grok_exe() -> Path:
    if os.name != "nt":
        home = _default_windows_home()
        if home:
            exe = home / ".grok" / "bin" / "grok.exe"
            if exe.exists():
                return exe
    return Path.home() / ".grok" / "bin" / "grok.exe"


def _default_sessions_dir() -> Path:
    if os.name != "nt":
        home = _default_windows_home()
        if home:
            sessions = home / ".grok" / "sessions"
            if sessions.exists():
                return sessions
    return Path.home() / ".grok" / "sessions"


def _split_scene_blocks(prompt_text: str) -> list[str]:
    blocks = [b.strip() for b in prompt_text.replace("\r\n", "\n").split("\n\n")]
    return [b for b in blocks if b]


def _find_newest_mp4(sessions_dir: Path, since_ts: float) -> Path | None:
    if not sessions_dir.exists():
        return None
    candidates: list[Path] = []
    for p in sessions_dir.rglob("*.mp4"):
        try:
            st = p.stat()
            if st.st_mtime >= since_ts and st.st_size > 100_000:
                candidates.append(p)
        except Exception:
            continue
    if not candidates:
        return None
    return max(candidates, key=lambda x: x.stat().st_mtime)


def _wait_stable(path: Path, checks: int = 3, interval: float = 1.3, timeout_sec: int = 60) -> bool:
    deadline = time.time() + timeout_sec
    last = -1
    stable = 0
    while time.time() < deadline:
        try:
            size = path.stat().st_size if path.exists() else 0
        except Exception:
            size = 0
        if size > 100_000 and size == last:
            stable += 1
            if stable >= checks:
                return True
        else:
            stable = 0
        last = size
        time.sleep(interval)
    return False


def _extract_last_frame(ffmpeg: Path, video_path: Path, out_png: Path) -> None:
    cmd = [
        str(ffmpeg),
        "-y",
        "-sseof",
        "-0.2",
        "-i",
        str(video_path),
        "-vframes",
        "1",
        "-update",
        "1",
        str(out_png),
    ]
    subprocess.run(cmd, check=False, capture_output=True, text=True)


def _default_style_rules(duration_seconds: int) -> str:
    return (
        "STYLE RULES (must apply in this scene):\n"
        "- Hand-drawn doodle neon animation style on a pure black background.\n"
        "- Expressive off-white chalk-marker outlines, imperfect sketch strokes, playful stick-figure characters with exaggerated emotions and gestures.\n"
        "- Bright pastel accent colors: yellow, mint, coral, sky blue, lavender as animated blobs, arrows, highlights, underlines.\n"
        "- Smooth 2D motion graphics, energetic kinetic typography, bouncing labels, popping keywords, fast transitions.\n"
        "- Psychology-themed infographic visuals: animated brain icons, hearts, thought clouds, chat bubbles, checklists, arrows, dopamine symbols, mood meters, abstract emotional diagrams.\n"
        "- Dynamic motion: rapid sketch reveals, scribble transitions, zoom-ins, floating icons, elastic motion.\n"
        "- Clean minimalist composition, high contrast, lots of negative space.\n"
        "- Fun educational modern explainer aesthetic.\n\n"
        "NEGATIVE RULES:\n"
        "- No photorealism\n"
        "- No 3D rendering\n"
        "- No cinematic shadows\n"
        "- No realistic humans\n"
        "- No lip-sync dialogue\n"
        "- No dark tones\n"
        "- No narration voice\n"
        "- Audio intent only: upbeat background music + marker drawing/paper scribble/pop/whoosh/tap/subtle ambient motion SFX.\n\n"
        "VIDEO OUTPUT RULES:\n"
        "- Duration exactly 6 seconds\n"
        "- Resolution 480p\n"
        "- Aspect ratio 9:16\n"
        "- One scene per output video"
    ).replace("Duration exactly 6 seconds", f"Duration exactly {duration_seconds} seconds")


def _gen_prompt(scene_block: str, idx: int, prev_last_frame: Path | None, style_rules: str, duration_seconds: int) -> str:
    scene_rules = (
        style_rules.strip()
        if style_rules.strip()
        else _default_style_rules(duration_seconds)
    )
    base = (
        "Generate one video scene as MP4. "
        f"Strict output settings: duration {duration_seconds} seconds, resolution 480p, aspect ratio 9:16. "
        "Keep style and subject continuity with prior scene. "
    )
    if idx == 1 or prev_last_frame is None:
        continuity = "This is the opening scene."
    else:
        continuity = (
            "Continue directly from the previous scene end-frame. "
            "Match same character, lighting, camera direction, and motion trajectory."
        )
    return (
        f"{base}\n{continuity}\n\n{scene_rules}\n\n"
        f"Scene prompt:\n{scene_block}\n\n"
        "Return only the generated local MP4 path."
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate Grok scenes via CLI first, with continuity.")
    ap.add_argument("--prompt-file", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--max-scene-seconds", type=int, default=420)
    ap.add_argument("--duration-seconds", type=int, default=6)
    ap.add_argument("--style-rules-file", default="")
    ap.add_argument("--grok-exe", default="")
    ap.add_argument("--sessions-dir", default="")
    ap.add_argument(
        "--ffmpeg",
        default=r"C:\Users\Saurabh\Documents\AutoVideoAgent\tools\ffmpeg\ffmpeg-8.1.1-essentials_build\bin\ffmpeg.exe",
    )
    args = ap.parse_args()

    prompt_file = Path(args.prompt_file)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    grok_exe = Path(args.grok_exe) if str(args.grok_exe or "").strip() else _default_grok_exe()
    sessions_dir = Path(args.sessions_dir) if str(args.sessions_dir or "").strip() else _default_sessions_dir()
    ffmpeg = Path(args.ffmpeg)

    if not prompt_file.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_file}")
    if not grok_exe.exists():
        raise FileNotFoundError(f"Grok CLI not found: {grok_exe}")

    event_path = output_dir / "grok_outputs.done.json"
    if event_path.exists():
        event_path.unlink()

    text = prompt_file.read_text(encoding="utf-8-sig")
    scenes = _split_scene_blocks(text)
    if not scenes:
        raise RuntimeError("No scene blocks found in prompt file.")
    style_rules = ""
    if args.style_rules_file:
        style_path = Path(args.style_rules_file)
        if not style_path.exists():
            raise FileNotFoundError(f"Style rules file not found: {style_path}")
        style_rules = style_path.read_text(encoding="utf-8-sig")
    duration_seconds = max(1, int(args.duration_seconds))

    produced: list[Path] = []
    prev_last_frame: Path | None = None

    for i, scene_block in enumerate(scenes, start=1):
        scene_prompt = _gen_prompt(scene_block, i, prev_last_frame, style_rules, duration_seconds)
        scene_prompt_file = output_dir / f"scene_{i:02d}.prompt.txt"
        scene_prompt_file.write_text(scene_prompt, encoding="utf-8")

        since = time.time()
        proc = subprocess.Popen(
            [str(grok_exe), "-p", scene_prompt],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        found: Path | None = None
        deadline = time.time() + max(60, int(args.max_scene_seconds))
        proc_out = ""
        proc_err = ""
        while time.time() < deadline:
            candidate = _find_newest_mp4(sessions_dir, since - 1.0)
            if candidate is not None and _wait_stable(candidate):
                found = candidate
                break
            if proc.poll() is not None:
                try:
                    o, e = proc.communicate(timeout=2)
                    proc_out = (o or "").strip()
                    proc_err = (e or "").strip()
                except Exception:
                    pass
                # Do not break immediately; keep polling until deadline because
                # Grok can finalize media file after process output returns.
            time.sleep(2.0)

        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()

        if found is None:
            raise RuntimeError(
                f"Grok CLI failed to produce scene {i}/{len(scenes)}.\n"
                f"STDOUT:\n{proc_out[:1200]}\nSTDERR:\n{proc_err[:1200]}"
            )

        out_scene = output_dir / f"grok_scene_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{i}.mp4"
        shutil.copy2(found, out_scene)
        produced.append(out_scene)

        prev_last_frame = output_dir / f"scene_{i:02d}_last_frame.png"
        if ffmpeg.exists():
            _extract_last_frame(ffmpeg, out_scene, prev_last_frame)
            if not prev_last_frame.exists():
                prev_last_frame = None

    payload = {
        "status": "ok",
        "mode": "cli_primary",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expected_count": len(scenes),
        "moved_count": len(produced),
        "files": [str(p) for p in produced],
        "output_dir": str(output_dir),
    }
    event_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n".join(str(p) for p in produced))


if __name__ == "__main__":
    main()
