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


def _find_newest_image(sessions_dir: Path, since_ts: float, exclude: set[str] | None = None) -> Path | None:
    exclude = exclude or set()
    if not sessions_dir.exists():
        return None
    exts = {".png", ".jpg", ".jpeg", ".webp"}
    candidates: list[Path] = []
    for p in sessions_dir.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in exts:
            continue
        if str(p.resolve()) in exclude:
            continue
        try:
            st = p.stat()
            if st.st_mtime >= since_ts and st.st_size > 40_000:
                candidates.append(p)
        except Exception:
            continue
    if not candidates:
        return None
    return max(candidates, key=lambda x: x.stat().st_mtime)


def _wait_stable(path: Path, checks: int = 3, interval: float = 1.0, timeout_sec: int = 40) -> bool:
    deadline = time.time() + timeout_sec
    last = -1
    stable = 0
    while time.time() < deadline:
        try:
            size = path.stat().st_size if path.exists() else 0
        except Exception:
            size = 0
        if size > 40_000 and size == last:
            stable += 1
            if stable >= checks:
                return True
        else:
            stable = 0
        last = size
        time.sleep(interval)
    return False


def _scene_prompt(scene_block: str, idx: int) -> str:
    rules = (
        "Generate ONE image only.\n"
        "Portrait composition suitable for 9:16 reel framing.\n"
        "This image should represent the crux of a 6-second scene.\n"
        "Hand-drawn doodle neon animation style on pure black background.\n"
        "Off-white chalk-marker outlines, playful stick figures, pastel accents.\n"
        "No photorealism, no 3D, no realistic humans, no cinematic shadows.\n"
    )
    continuity = "Opening scene image." if idx == 1 else "Keep continuity with prior scene style and subject."
    return (
        f"{rules}\n{continuity}\n\n"
        f"Scene prompt:\n{scene_block}\n\n"
        "Return only generated local image path."
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate scene images via Grok CLI from scene blocks.")
    ap.add_argument("--prompt-file", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--max-scene-seconds", type=int, default=420)
    ap.add_argument("--grok-exe", default="")
    ap.add_argument("--sessions-dir", default="")
    args = ap.parse_args()

    prompt_file = Path(args.prompt_file)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    grok_exe = Path(args.grok_exe) if str(args.grok_exe or "").strip() else _default_grok_exe()
    sessions_dir = Path(args.sessions_dir) if str(args.sessions_dir or "").strip() else _default_sessions_dir()
    if not prompt_file.exists():
        raise FileNotFoundError(f"Prompt file missing: {prompt_file}")
    if not grok_exe.exists():
        raise FileNotFoundError(f"Grok CLI missing: {grok_exe}")

    event_path = output_dir / "grok_outputs.done.json"
    if event_path.exists():
        event_path.unlink()

    scenes = _split_scene_blocks(prompt_file.read_text(encoding="utf-8-sig"))
    if not scenes:
        raise RuntimeError("No scene blocks found.")

    outputs: list[Path] = []
    consumed_sources: set[str] = set()
    for i, block in enumerate(scenes, start=1):
        wrapped = _scene_prompt(block, i)
        (output_dir / f"scene_{i:02d}.prompt.txt").write_text(wrapped, encoding="utf-8")
        since = time.time()
        proc = subprocess.Popen([str(grok_exe), "-p", wrapped], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        found: Path | None = None
        deadline = time.time() + int(args.max_scene_seconds)
        out = err = ""
        while time.time() < deadline:
            candidate = _find_newest_image(sessions_dir, since - 1.0, consumed_sources)
            if candidate is not None and _wait_stable(candidate):
                found = candidate
                break
            if proc.poll() is not None:
                try:
                    out, err = proc.communicate(timeout=2)
                except Exception:
                    pass
            time.sleep(2.0)
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
        if found is None:
            raise RuntimeError(f"Scene image generation failed at {i}/{len(scenes)}\nSTDOUT:\n{out[:800]}\nSTDERR:\n{err[:800]}")

        dst = output_dir / f"grok_scene_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{i}{found.suffix.lower()}"
        # WSL can read Windows Grok outputs but may fail copying Windows metadata.
        # Copy bytes only so cross-filesystem metadata permissions cannot fail the run.
        shutil.copyfile(found, dst)
        consumed_sources.add(str(found.resolve()))
        outputs.append(dst)

    payload = {
        "status": "ok",
        "mode": "cli_scene_images",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expected_count": len(scenes),
        "moved_count": len(outputs),
        "files": [str(p) for p in outputs],
        "output_dir": str(output_dir),
    }
    event_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n".join(str(p) for p in outputs))


if __name__ == "__main__":
    main()
