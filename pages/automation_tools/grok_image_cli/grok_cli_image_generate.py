from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def _candidate_grok_paths() -> list[Path]:
    home = Path.home()
    return [
        home / ".grok" / "bin" / "grok.exe",
        Path("/mnt/c/Users/Saurabh/.grok/bin/grok.exe"),
        Path(r"C:\Users\Saurabh\.grok\bin\grok.exe"),
    ]


def _candidate_session_paths() -> list[Path]:
    home = Path.home()
    return [
        home / ".grok" / "sessions",
        Path("/mnt/c/Users/Saurabh/.grok/sessions"),
        Path(r"C:\Users\Saurabh\.grok\sessions"),
    ]


def _resolve_existing(path_text: str | None, candidates: list[Path], label: str) -> Path:
    if path_text:
        path = Path(path_text)
        if path.exists():
            return path
    for candidate in candidates:
        if candidate.exists():
            return candidate
    checked = "\n".join(str(candidate) for candidate in candidates)
    raise FileNotFoundError(f"{label} missing. Checked:\n{checked}")


def _find_newest_image(sessions_dir: Path, since_ts: float) -> Path | None:
    if not sessions_dir.exists():
        return None
    exts = {".png", ".jpg", ".jpeg", ".webp"}
    candidates: list[Path] = []
    for p in sessions_dir.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in exts:
            continue
        try:
            st = p.stat()
            if st.st_mtime >= since_ts and st.st_size > 30_000:
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
        if size > 30_000 and size == last:
            stable += 1
            if stable >= checks:
                return True
        else:
            stable = 0
        last = size
        time.sleep(interval)
    return False


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate one image using Grok CLI.")
    ap.add_argument("--prompt-file", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--max-wait-seconds", type=int, default=420)
    ap.add_argument("--grok-exe", default=str(Path.home() / ".grok" / "bin" / "grok.exe"))
    ap.add_argument("--sessions-dir", default=str(Path.home() / ".grok" / "sessions"))
    args = ap.parse_args()

    prompt_file = Path(args.prompt_file)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    grok_exe = _resolve_existing(args.grok_exe, _candidate_grok_paths(), "Grok CLI")
    sessions_dir = _resolve_existing(args.sessions_dir, _candidate_session_paths(), "Grok sessions directory")
    if not prompt_file.exists():
        raise FileNotFoundError(f"Prompt file missing: {prompt_file}")

    prompt = prompt_file.read_text(encoding="utf-8-sig").strip()
    wrapped = (
        "Generate one image.\n"
        "Output settings: portrait 9:16 composition, 480p-compatible framing.\n"
        f"Prompt:\n{prompt}\n\n"
        "Return only the generated local image path."
    )
    since = time.time()
    proc = subprocess.Popen([str(grok_exe), "-p", wrapped], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")

    found: Path | None = None
    deadline = time.time() + int(args.max_wait_seconds)
    out = err = ""
    while time.time() < deadline:
        candidate = _find_newest_image(sessions_dir, since - 1.0)
        if candidate is not None and _wait_stable(candidate):
            found = candidate
            break
        if proc.poll() is not None:
            try:
                out, err = proc.communicate(timeout=2)
            except Exception:
                pass
        time.sleep(2)

    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

    if found is None:
        raise RuntimeError(f"Grok image generation failed.\nSTDOUT:\n{out[:1200]}\nSTDERR:\n{err[:1200]}")

    out_img = out_dir / f"grok_image_{datetime.now().strftime('%Y%m%d_%H%M%S')}{found.suffix.lower()}"
    # WSL can fail copying Windows file timestamps from Grok's session folder.
    # Copy bytes only; fresh metadata is recorded in the done manifest below.
    shutil.copyfile(found, out_img)
    event = {
        "status": "ok",
        "mode": "cli_image",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": str(found),
        "output": str(out_img),
    }
    (out_dir / "grok_image.done.json").write_text(json.dumps(event, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(out_img))


if __name__ == "__main__":
    main()
