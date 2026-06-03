from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PAGE_KEY = "page4_relationship"


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


def _wsl_to_windows_path(value: str | Path) -> str:
    text = str(value).replace("\\", "/")
    if os.name != "nt" and text.startswith("/mnt/") and len(text) > 6 and text[6] == "/":
        return f"{text[5].upper()}:/{text[7:]}"
    return str(value)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_first_json_blob(text: str) -> dict:
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*```$", "", t)
    try:
        return json.loads(t)
    except Exception:
        pass
    dec = json.JSONDecoder()
    for i, ch in enumerate(t):
        if ch != "{":
            continue
        try:
            obj, _end = dec.raw_decode(t[i:])
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue
    m = re.search(r"\{[\s\S]*\}", t)
    if not m:
        raise RuntimeError("No JSON object found in model output.")
    return json.loads(m.group(0))


def _repair_mojibake(s: str) -> str:
    t = str(s or "")
    # Typical UTF-8->cp1252 mojibake signatures.
    if any(x in t for x in ("Ã", "â€™", "â€œ", "â€", "ðŸ", "Å")):
        try:
            t = t.encode("latin1", errors="ignore").decode("utf-8", errors="ignore")
        except Exception:
            pass
    return t


def _normalize_text(s: str) -> str:
    t = _repair_mojibake(str(s or ""))
    # Convert escaped newlines into real line breaks when model emits "\\n".
    t = t.replace("\\r\\n", "\n").replace("\\n", "\n")
    # Normalize line endings.
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    # Remove zero-width chars that can appear in copied model output.
    t = t.replace("\u200b", "").replace("\ufeff", "")
    return t.strip()


def _normalize_payload(obj):
    if isinstance(obj, dict):
        return {k: _normalize_payload(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_normalize_payload(v) for v in obj]
    if isinstance(obj, str):
        return _normalize_text(obj)
    return obj


def _run_grok_text(prompt: str) -> str:
    grok_exe = _default_grok_exe()
    if not grok_exe.exists():
        raise RuntimeError(f"Grok CLI not found: {grok_exe}")
    p = subprocess.run([str(grok_exe), "-p", prompt], capture_output=True, text=True)
    combined = f"{p.stdout or ''}\n{p.stderr or ''}".lower()
    limit_signals = [
        "rate limit",
        "rate-limit",
        "exceeded",
        "too many requests",
        "quota",
        "limit reached",
        "try again later",
    ]
    if any(sig in combined for sig in limit_signals):
        raise RuntimeError("GROK_LIMIT_REACHED: Grok rate/quota limit detected. Failing without fallback.")
    if p.returncode != 0:
        raise RuntimeError(f"grok text generation failed\nSTDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}")
    return (p.stdout or "").strip()


def _generate_content_json() -> dict:
    prompt = """
You are generating short-form relationship reel content.

Source-of-truth rule:
- Content principles must be derived ONLY from teachings associated with these three sources:
  1) Corey Wayne
  2) The Gottman Institute
  3) Esther Perel
- Do NOT mention any person/institute names in final output text.

Output STRICT JSON only with this schema:
{
  "hook_used": "...",
  "narration_text": "...",
  "caption_text": "...",
  "hashtags": ["#tag1", "#tag2", "#tag3"]
}

Hard constraints:
- narration_text: about 90-110 words, <1 minute speech, one strong opening hook.
- caption_text: engagement-focused, concise, with CTA question.
- hashtags: 20-30 tags, high-RPM relationship/self-improvement mix, US-audience intent.
- Keep language clear and practical.
- Do not include any banned source names in narration/caption/hashtags.

Allowed hook styles (use one or similar):
- People are obsessed with [thing] and I can see why...
- Apparently, people still don’t know this...
- Every [avatar] needs to [mechanism].
- You’ve been doing [practice] ALL WRONG.
- STOP doing [old method] and do THIS instead.
- Why is [outcome] so hard? Let’s talk about it.
- Think [objection]? Think again.

No markdown. JSON only.
""".strip()

    payload = _extract_first_json_blob(_run_grok_text(prompt))
    payload = _normalize_payload(payload)

    narration = _normalize_text(payload.get("narration_text", ""))
    caption = _normalize_text(payload.get("caption_text", ""))
    hashtags = payload.get("hashtags", [])
    if not isinstance(hashtags, list):
        raise RuntimeError("Invalid hashtags in Grok JSON")
    hashtags = [_normalize_text(h) for h in hashtags if _normalize_text(h)]

    banned = ["corey wayne", "gottman", "esther perel"]
    joined = (narration + "\n" + caption + "\n" + " ".join(hashtags)).lower()
    for b in banned:
        if b in joined:
            raise RuntimeError(f"Generated content contains banned source name: {b}")

    wc = len(re.findall(r"\b\w+\b", narration))
    if wc < 70 or wc > 140:
        raise RuntimeError(f"Narration length out of range: {wc} words")
    if len(hashtags) < 10:
        raise RuntimeError("Too few hashtags generated")

    return {
        "hook_used": str(payload.get("hook_used", "")).strip(),
        "narration_text": narration,
        "caption_text": caption,
        "hashtags": hashtags,
    }


def _probe_audio_seconds(ffprobe_exe: Path, audio_file: Path) -> float:
    cmd = [
        str(ffprobe_exe),
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(audio_file),
    ]
    if os.name != "nt" and str(ffprobe_exe).lower().endswith(".exe"):
        cmd = [cmd[0], *[_wsl_to_windows_path(x) for x in cmd[1:]]]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {audio_file}\nSTDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}")
    try:
        return float((p.stdout or "0").strip())
    except Exception:
        return 0.0


def _generate_scenes_json_with_grok(narration: str, scene_count: int) -> dict:
    prompt = f"""
You are creating scene prompts for an AI video reel pipeline.

Task:
- Convert the narration into exactly {scene_count} scene prompts.
- Keep continuity and progression from one scene to the next.
- Output STRICT JSON only (no markdown, no explanation).

STYLE RULES (must apply to every scene):
- Hand-drawn doodle neon animation style on a pure black background.
- Expressive off-white chalk-marker outlines, imperfect sketch strokes, playful stick-figure characters with exaggerated emotions and gestures.
- Bright pastel accent colors: yellow, mint, coral, sky blue, lavender as animated blobs, arrows, highlights, underlines.
- Smooth 2D motion graphics, energetic kinetic typography, bouncing labels, popping keywords, fast transitions.
- Psychology-themed infographic visuals: animated brain icons, hearts, thought clouds, chat bubbles, checklists, arrows, dopamine symbols, mood meters, abstract emotional diagrams.
- Dynamic intro-style motion vocabulary: rapid sketch reveals, scribble transitions, zoom-ins, floating icons, elastic motion.
- Clean minimalist composition, high contrast, lots of negative space.
- Fun educational modern explainer aesthetic.
- Medium-density composition (not crowded).
- Max 4 major visual elements on screen per scene.
- At most 2 text callouts/keywords on screen per scene.
- Strict RULE - Reserve roughly 40-50% negative space.
- Prioritize one clear focal subject per scene.

NEGATIVE RULES:
- No photorealism
- No 3D rendering
- No cinematic shadows
- No realistic humans
- No lip-sync dialogue
- No dark tones
- No narration voice
- Audio intent only: upbeat background music + marker drawing/paper scribble/pop/whoosh/tap/subtle ambient motion SFX.

FORMAT RULES:
- Each scene must contain 6-7 descriptive lines.
- Do not include "Scene 1:" labels inside lines.

Required JSON schema:
{{
  "scene_count": {scene_count},
  "scenes": [
    {{
      "index": 1,
      "lines": ["line 1", "line 2", "line 3", "line 4", "line 5", "line 6"]
    }}
  ]
}}

Hard constraints:
- scenes length MUST be exactly {scene_count}
- each scenes[i].lines length MUST be 6 or 7
- no extra keys outside this structure

Narration:
{narration}
""".strip()

    payload = _extract_first_json_blob(_run_grok_text(prompt))
    payload = _normalize_payload(payload)
    scenes = payload.get("scenes")
    if not isinstance(scenes, list):
        raise RuntimeError("Invalid Grok JSON: missing 'scenes' list.")
    if len(scenes) != scene_count:
        raise RuntimeError(f"Invalid Grok JSON: expected {scene_count} scenes, got {len(scenes)}")
    for i, s in enumerate(scenes, start=1):
        lines = (s or {}).get("lines")
        if not isinstance(lines, list):
            raise RuntimeError(f"Invalid Grok JSON: scene {i} missing lines list.")
        if len(lines) < 6 or len(lines) > 7:
            raise RuntimeError(f"Invalid Grok JSON: scene {i} must have 6-7 lines, got {len(lines)}")
    return payload


def _fallback_scenes_from_narration(narration: str, scene_count: int) -> dict:
    parts = [x.strip() for x in re.split(r"(?<=[.!?])\s+", narration.strip()) if x.strip()]
    if not parts:
        parts = [narration.strip() or "Relationship insight scene."]
    chunks: list[str] = []
    for i in range(scene_count):
        chunks.append(parts[i % len(parts)])
    scenes: list[dict] = []
    for i, ch in enumerate(chunks, start=1):
        lines = [
            "Hand-drawn doodle neon scene on pure black background.",
            "Off-white chalk-marker stick figures with expressive emotions.",
            "Pastel accents: yellow, mint, coral, sky blue, lavender.",
            "Kinetic typography emphasizes key words from this beat.",
            f"Narrative focus: {ch}",
            "Clean high-contrast composition with generous negative space.",
        ]
        scenes.append({"index": i, "lines": lines})
    return {"scene_count": scene_count, "scenes": scenes}


def _scene_json_to_prompt_text(scene_payload: dict) -> str:
    scenes = scene_payload.get("scenes") or []
    blocks: list[str] = []
    for i, s in enumerate(scenes, start=1):
        raw_lines = (s or {}).get("lines") or []
        cleaned = [str(x).strip() for x in raw_lines if str(x).strip()]
        if len(cleaned) < 6 or len(cleaned) > 7:
            raise RuntimeError(f"Scene {i} lines must remain 6-7 after cleanup, got {len(cleaned)}")
        blocks.append("\n".join(cleaned))
    return "\n\n".join(blocks).strip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Prepare page4 narration + voice + Grok scene prompt text (AI-only, no DB/Excel)")
    ap.add_argument("--voice-json", default=str(PROJECT_ROOT / "pages" / PAGE_KEY / "content" / "voice_profile.json"))
    ap.add_argument("--ffprobe", default=str(PROJECT_ROOT / "tools" / "ffmpeg" / "ffmpeg-8.1.1-essentials_build" / "bin" / "ffprobe.exe"))
    args = ap.parse_args()

    now = datetime.now()
    run_dir = PROJECT_ROOT / "runs" / now.strftime("%Y-%m-%d") / PAGE_KEY / now.strftime("%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)

    content_json = _generate_content_json()
    item_id = int(datetime.now().strftime("%H%M%S"))

    narration_txt = run_dir / f"narration_{item_id}.txt"
    voice_mp3 = run_dir / f"voice_{item_id}.mp3"
    scene_prompt_txt = run_dir / f"scene_prompts_{item_id}.txt"
    scene_prompt_json = run_dir / f"scene_prompts_{item_id}.json"
    content_json_file = run_dir / f"content_{item_id}.json"
    grok_output_dir = run_dir / "grok_outputs"
    grok_output_dir.mkdir(parents=True, exist_ok=True)

    narration_txt.write_text(content_json["narration_text"].strip() + "\n", encoding="utf-8")
    content_json_file.write_text(json.dumps(content_json, ensure_ascii=False, indent=2), encoding="utf-8")

    cmd = [
        "powershell",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(PROJECT_ROOT / "pages" / "automation_tools" / "speechma" / "speechma_run.ps1"),
        str(narration_txt),
        str(Path(args.voice_json)),
        str(voice_mp3),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, shell=False)
    if proc.returncode != 0:
        raise RuntimeError(f"speechma_run failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")

    voice_seconds = _probe_audio_seconds(Path(args.ffprobe), voice_mp3)
    scene_count = max(1, int(math.ceil(max(1.0, voice_seconds) / 6.0)))

    scenes_json = _generate_scenes_json_with_grok(content_json["narration_text"], scene_count)
    scene_prompt_json.write_text(json.dumps(scenes_json, ensure_ascii=False, indent=2), encoding="utf-8")

    scene_prompt_text = _scene_json_to_prompt_text(scenes_json)
    scene_prompt_txt.write_text(scene_prompt_text, encoding="utf-8")

    manifest = {
        "page": PAGE_KEY,
        "item_id": item_id,
        "content_json": str(content_json_file),
        "narration_txt": str(narration_txt),
        "voice_mp3": str(voice_mp3),
        "voice_seconds": voice_seconds,
        "scene_count": scene_count,
        "scene_prompt_json": str(scene_prompt_json),
        "scene_prompt_txt": str(scene_prompt_txt),
        "grok_output_dir": str(grok_output_dir),
        "caption": content_json["caption_text"],
        "hashtags": " ".join(content_json["hashtags"]),
        "hook_used": content_json.get("hook_used", ""),
        "created_at": now_iso(),
    }
    manifest_path = run_dir / f"page4_prepare_{item_id}.manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"PAGE={PAGE_KEY}")
    print(f"ITEM_ID={item_id}")
    print(f"CONTENT_JSON={content_json_file}")
    print(f"NARRATION_TXT={narration_txt}")
    print(f"VOICE_MP3={voice_mp3}")
    print(f"VOICE_SECONDS={voice_seconds}")
    print(f"SCENE_COUNT={scene_count}")
    print(f"SCENE_PROMPT_JSON={scene_prompt_json}")
    print(f"SCENE_PROMPT_TXT={scene_prompt_txt}")
    print(f"GROK_OUTPUT_DIR={grok_output_dir}")
    print(f"MANIFEST={manifest_path}")


if __name__ == "__main__":
    main()
