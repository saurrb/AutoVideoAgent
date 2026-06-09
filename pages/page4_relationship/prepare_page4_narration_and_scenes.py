from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PAGE_KEY = "page4_relationship"
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autovideo.services.grok_cli import run_grok_text  # noqa: E402
from autovideo.services.text_utils import extract_json_object, normalize_payload, normalize_text  # noqa: E402


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
    return extract_json_object(text)


def _repair_mojibake(s: str) -> str:
    return normalize_text(s)


def _normalize_text(s: str) -> str:
    return normalize_text(s)


def _normalize_payload(obj):
    return normalize_payload(obj)


def _run_grok_text(prompt: str) -> str:
    return run_grok_text(prompt, grok_exe=_default_grok_exe(), cwd=PROJECT_ROOT).strip()


def _extract_json_with_retry(prompt: str, *, retry_instruction: str) -> dict:
    raw = _run_grok_text(prompt)
    try:
        return _extract_first_json_blob(raw)
    except Exception as first_error:
        repair_prompt = f"""
Your previous response was not parseable JSON.

Original task:
{prompt}

Return ONLY valid JSON now. Do not include markdown, explanation, headings, bullets, or commentary.
{retry_instruction}
""".strip()
        raw_retry = _run_grok_text(repair_prompt)
        try:
            return _extract_first_json_blob(raw_retry)
        except Exception as retry_error:
            raise RuntimeError(
                "Grok did not return valid JSON after retry. "
                f"First error: {first_error}. Retry error: {retry_error}. "
                f"First output preview: {raw[:600]!r}. Retry output preview: {raw_retry[:600]!r}"
            ) from retry_error


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
- narration_text: about 150-200 words, one strong opening hook.
- caption_text: engagement-focused, concise, with CTA question.
- hashtags: 10-15 tags, high-RPM relationship/self-improvement mix, US-audience intent.
- Keep language clear and practical.
- Do not include any banned source names in narration/caption/hashtags.
- First sentence must create strong emotional tension or a pattern interrupt.
- Prefer "ouch, that is true" insights over generic advice.
- Use a clear mini-arc: hook -> common mistake -> emotional consequence -> better rule -> memorable closing line.
- Keep monetization-safe language: relationship psychology, self-respect, boundaries, communication, confidence, emotional maturity.

Allowed hook styles (use one or similar):
- People are obsessed with [thing] and I can see why...
- Apparently, people still don’t know this...
- Every [avatar] needs to [mechanism].
- You’ve been doing [practice] ALL WRONG.
- STOP doing [old method] and do THIS instead.
- Why is [outcome] so hard? Let’s talk about it.
- Think [objection]? Think again.
- Most people confuse [healthy thing] with [unhealthy thing].
- If you are always [old behavior], [desired outcome] quietly fades.
- The fastest way to lose [value] is chasing [approval/attention/validation].
- Healthy love does not feel like [emotional panic/control/confusion].

No markdown. JSON only. The first character of your response must be { and the last character must be }.
""".strip()

    payload = _extract_json_with_retry(
        prompt,
        retry_instruction=(
            'Required schema: {"hook_used":"...","narration_text":"...",'
            '"caption_text":"...","hashtags":["#tag1","#tag2"]}'
        ),
    )
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
    if wc < 130 or wc > 230:
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


def _character_bible() -> str:
    return """
STRICT CHARACTER CONTINUITY BIBLE:
Maya: adult woman, smooth white circular face, tiny black dot/line eyes, expressive worried brows, tiny mouth, short black bob haircut tucked behind ears, slim simplified body. Keep the same face shape, black bob, proportions, and serious emotional expression language in every image. Her outfit may vary slightly within a muted dark palette: charcoal, slate, deep olive, black, soft brown; modern simple relationship-cartoon clothing only.
Leo: adult man, smooth white circular face, tiny black dot/line eyes, expressive worried brows, tiny mouth, short neat black hair, slim simplified body. Keep the same face shape, neat black hair, proportions, and serious emotional expression language in every image. His outfit may vary slightly within a muted dark palette: navy, charcoal, black, dark grey, muted brown; modern simple relationship-cartoon clothing only.
No analyst. No narrator. No therapist. No observer. No clipboard. No extra third character unless the narration beat genuinely requires a memory silhouette or symbolic background figure.
""".strip()


def _triptych_style_rules() -> str:
    return """
Generate one image only. LANDSCAPE 16:9 wide illustrated cartoon triptych, not portrait.
STRICT COMPOSITION RULES:
1. The image must have exactly three readable emotional beats: LEFT SECTION, CENTER SECTION, RIGHT SECTION. They may be separated by lighting, doorway, furniture, shadows, window frames, reflections, or composition; they do not need harsh comic borders.
2. Each section must show a different moment, pose, thought, or emotional action. Do not repeat the same pose three times.
3. Each section must include its own visible red glow or red emotional light line. Red glow must appear in left, center, and right sections.
4. The three sections should feel like consecutive emotional beats flowing left to right.
5. Each section must work as an independent vertical 9:16 crop.

Creative freedom:
- Sometimes show a direct story moment between Maya and Leo.
- Sometimes show Maya or Leo alone with their thoughts, fears, or emotional realizations.
- The visual can be literal or metaphorical, but it must stay grounded in the relationship situation.
- Use symbolic relationship objects when useful: unread phone messages, two coffee cups, closed doors, rain on a window, an empty chair, framed photo, hallway shadows, a cracked mirror reflection, a half-lit bed, keys on a table, or a calendar reminder.
- Vary camera language: wide shot, close-up on hands, over-the-shoulder view, window reflection, doorway silhouette, top-down table shot, side profile, almost-touching hands, or a distant couch composition.
- Emotional actions can include turning away, deleting a message, waiting by the phone, reaching but stopping, sitting apart, looking at an old photo, standing in a doorway, soft repair, guarded arms, or hesitant eye contact.
- No separate explaining character. The real people in the problem are the characters.

Visual style: simple premium relationship cartoon. Smooth white circular faces, tiny black dot/line eyes, worried brows, tiny mouth. Slim simplified adult bodies, modern dark clothes, crisp black outlines, clean shapes.
Environment: same dark blue-black emotional visual universe across all images. Locations may vary naturally: dim apartment, bedroom edge, kitchen table, hallway, rainy window, parked car at night, empty cafe corner, phone-lit room, or living room couch. Keep the premium dark relationship-psychology mood, textured walls, soft shadows, warm rim light. Red emotional glow/line is the brand motif.
Mood: serious relationship psychology, emotional distance, vulnerability, anxiety, repair. Strong emotion in posture: slumped shoulders, hesitant hands, looking away, guarded arms, soft eye contact, relief.
Important: NOT photorealistic, NOT anime, NOT manga, NOT chibi, NOT purple hair, NOT superhero, NOT fantasy, NOT cute childish cartoon, NOT 3D, NOT realistic human faces.
No text, no captions, no letters, no signs, no watermark, no logo, no speech bubbles.
""".strip()


def _generate_scenes_json_with_grok(narration: str, scene_count: int) -> dict:
    prompt = f"""
You are creating image prompts for a premium relationship psychology reel.

Task:
- Convert the narration into exactly {scene_count} LANDSCAPE 16:9 triptych image prompts.
- Each image prompt must describe one wide image containing exactly three readable emotional beats: LEFT, CENTER, RIGHT.
- Every image must preserve strict Maya/Leo continuity.
- The images may be story-based or thought/emotion-based, depending on the narration beat.
- Use the full wide image like a left-to-right emotional story strip for smooth panning.
- Output STRICT JSON only (no markdown, no explanation).

Required JSON schema:
{{
  "scene_count": {scene_count},
  "scenes": [
    {{
      "index": 1,
      "beat": "short narration beat this image covers",
      "left_section": "beginning thought/action, with red glow",
      "center_section": "strongest emotional moment, with red glow",
      "right_section": "next emotional consequence or repair, with red glow"
    }}
  ]
}}

Hard constraints:
- scenes length MUST be exactly {scene_count}
- each scene must have beat, left_section, center_section, right_section
- section fields must describe ONLY actions, poses, emotions, symbolic props, camera angle, lighting separation, and environment details
- section fields must NOT describe hair, eyes, age, clothing color, outfit, face shape, body type, or character appearance
- section fields must NOT introduce any character design different from the fixed Maya/Leo bible
- no extra keys outside this structure
- each section must be different from the other two sections
- each section must include red glow/red emotional light line
- sections may be divided by doorway, window, couch, reflection, shadow, table, car window, hallway frame, or lighting rather than hard comic borders
- no analyst/narrator/therapist/observer character
- keep Maya and Leo visually consistent across all image prompts

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
    for i, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            raise RuntimeError(f"Invalid Grok JSON: scene {i} is not an object.")
        for key in ("beat", "left_section", "center_section", "right_section"):
            if not str(scene.get(key, "")).strip():
                raise RuntimeError(f"Invalid Grok JSON: scene {i} missing {key}.")
    return payload


def _fallback_scenes_from_narration(narration: str, scene_count: int) -> dict:
    parts = [x.strip() for x in re.split(r"(?<=[.!?])\s+", narration.strip()) if x.strip()]
    if not parts:
        parts = [narration.strip() or "Relationship anxiety shifts into repair."]
    scenes: list[dict] = []
    for i in range(scene_count):
        beat = parts[i % len(parts)]
        scenes.append({
            "index": i + 1,
            "beat": beat,
            "left_section": f"Maya or Leo quietly feels the tension from this beat: {beat}. Red glow appears near the body.",
            "center_section": "The emotional pressure becomes visible through posture, distance, or a red line between them.",
            "right_section": "A small repair attempt, realization, or calmer choice begins while the red glow softens.",
        })
    return {"scene_count": scene_count, "scenes": scenes}


def _strip_page4_character_overrides(text: str) -> str:
    """Keep Grok's action beat while removing appearance/clothing overrides."""
    t = _normalize_text(text)
    # Common pattern from scene-planning models: "Maya, an early 30s woman with ... , shares ...".
    # Replace the descriptive clause with the fixed character name so the bible remains authoritative.
    verbs = (
        "shares|pulls|reaches|feels|sits|stands|looks|turns|holds|walks|paces|stares|listens|asks|speaks|"
        "leans|crosses|softens|withdraws|waits|notices|tries|stops|faces|opens|closes|touches|checks"
    )
    t = re.sub(rf"\bMaya,\s+.*?,\s+({verbs})\b", r"Maya \1", t, flags=re.IGNORECASE)
    t = re.sub(rf"\bLeo,\s+.*?,\s+({verbs})\b", r"Leo \1", t, flags=re.IGNORECASE)
    # Remove remaining visual override phrases if Grok included them mid-sentence.
    t = re.sub(r"\b(an?|the)\s+(early|mid|late)\s+\d0s\s+(woman|man)\b", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\bwith\s+[^,.]*(hair|eyes|sweater|shirt|dress|jacket|pants|face|body)[^,.]*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\bwearing\s+[^,.]*", "", t, flags=re.IGNORECASE)
    t = re.sub(r",\s*,+", ",", t)
    t = re.sub(r"\s+,", ",", t)
    t = re.sub(r"\b(Maya|Leo),\s+", r"\1 ", t)
    t = re.sub(r"\s+", " ", t).strip(" ,")
    return t


def _scene_json_to_prompt_text(scene_payload: dict) -> str:
    scenes = scene_payload.get("scenes") or []
    blocks: list[str] = []
    bible = _character_bible()
    style = _triptych_style_rules()
    for i, scene in enumerate(scenes, start=1):
        beat = _normalize_text((scene or {}).get("beat", ""))
        left = _strip_page4_character_overrides((scene or {}).get("left_section", ""))
        center = _strip_page4_character_overrides((scene or {}).get("center_section", ""))
        right = _strip_page4_character_overrides((scene or {}).get("right_section", ""))
        if not (beat and left and center and right):
            raise RuntimeError(f"Scene {i} missing beat/section text after cleanup.")
        block = f"""
PAGE4_TRIPTYCH_PROMPT
{bible}

{style}

Scene {i} overall beat: {beat}

Design this beat as three different moments inside one image:
LEFT SECTION: {left}
CENTER SECTION: {center}
RIGHT SECTION: {right}

CRITICAL: Use ONLY the fixed Maya/Leo character bible for appearance. Ignore any accidental appearance detail in the section text. Do not invent hair, clothing, age, face, anime, manga, purple hair, superhero, fantasy, or doodle variants. Every output must be one 16:9 triptych image with exactly three sections and red glow in all three sections. Return only local generated image path.
""".strip()
        blocks.append(block)
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
    scene_count = max(3, min(5, int(math.ceil(max(1.0, voice_seconds) / 20.0))))

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
