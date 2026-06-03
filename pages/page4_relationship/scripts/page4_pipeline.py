from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PAGE_ROOT = PROJECT_ROOT / "pages" / "page4_relationship"


def _run(cmd: list[str], cwd: Path | None = None) -> str:
    p = subprocess.run(cmd, cwd=cwd or PROJECT_ROOT, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\\nSTDOUT:\\n{p.stdout}\\nSTDERR:\\n{p.stderr}")
    return p.stdout or ""


def _parse_key(stdout: str, key: str) -> str:
    pref = f"{key}="
    for ln in stdout.splitlines():
        if ln.startswith(pref):
            return ln.split("=", 1)[1].strip()
    raise RuntimeError(f"Missing {key}=... in output")


def _stage_write(run_dir: Path, stage: str, payload: dict) -> None:
    p = run_dir / "state"
    p.mkdir(parents=True, exist_ok=True)
    (p / f"{stage}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    started = datetime.now().isoformat(timespec="seconds")

    prep_out = _run([sys.executable, str(PAGE_ROOT / "prepare_page4_narration_and_scenes.py")])
    prep_manifest = Path(_parse_key(prep_out, "MANIFEST"))
    prep_payload = json.loads(prep_manifest.read_text(encoding="utf-8"))
    run_dir = prep_manifest.parent
    _stage_write(run_dir, "01_prepare", {
        "ok": True,
        "at": datetime.now().isoformat(timespec="seconds"),
        "manifest": str(prep_manifest),
        "voice_mp3": prep_payload.get("voice_mp3"),
        "scene_count": prep_payload.get("scene_count"),
    })

    scene_prompt_txt = Path(prep_payload["scene_prompt_txt"])
    grok_output_dir = Path(prep_payload["grok_output_dir"])
    _run([
        sys.executable,
        str(PROJECT_ROOT / "pages" / "automation_tools" / "grok_image_cli" / "grok_cli_scene_images_generate.py"),
        "--prompt-file", str(scene_prompt_txt),
        "--output-dir", str(grok_output_dir),
    ])
    _stage_write(run_dir, "02_generate", {
        "ok": True,
        "at": datetime.now().isoformat(timespec="seconds"),
        "grok_output_dir": str(grok_output_dir),
    })

    _run([
        sys.executable,
        str(PAGE_ROOT / "scripts" / "render_page4_singlepass.py"),
        "--manifest", str(prep_manifest),
    ])

    item_id = int(prep_payload.get("item_id", 0) or 0)
    final_mp4 = run_dir / f"page4_{item_id}_final_singlepass_720x1280.mp4"
    content_json = Path(prep_payload.get("content_json", ""))
    content = json.loads(content_json.read_text(encoding="utf-8-sig")) if content_json.exists() else {}
    caption = (str(content.get("caption_text", "")).strip() + "\\n\\n" + " ".join(content.get("hashtags", []) or [])).strip()

    out_manifest = {
        "page": "page4_relationship",
        "item_id": item_id,
        "output_mp4": str(final_mp4.resolve()),
        "caption": caption,
        "spec": {"points": [{"source_item_id": item_id}]},
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "started_at": started,
        "run_dir": str(run_dir),
    }
    out_path = run_dir / f"page4_{item_id}.manifest.json"
    out_path.write_text(json.dumps(out_manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    _stage_write(run_dir, "03_render", {
        "ok": True,
        "at": datetime.now().isoformat(timespec="seconds"),
        "video": str(final_mp4),
        "manifest": str(out_path),
    })

    print(f"MANIFEST={out_path}")
    print(f"VIDEO={final_mp4}")


if __name__ == "__main__":
    main()
