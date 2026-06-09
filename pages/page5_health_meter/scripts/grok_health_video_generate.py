from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def _candidate_paths() -> list[Path]:
    home = Path.home()
    return [
        home / ".grok" / "bin" / "grok.exe",
        Path("/mnt/c/Users/Saurabh/.grok/bin/grok.exe"),
        Path(r"C:\Users\Saurabh\.grok\bin\grok.exe"),
    ]


def _candidate_sessions() -> list[Path]:
    home = Path.home()
    return [
        home / ".grok" / "sessions",
        Path("/mnt/c/Users/Saurabh/.grok/sessions"),
        Path(r"C:\Users\Saurabh\.grok\sessions"),
    ]


def _resolve_existing(path_text: str | None, candidates: list[Path]) -> Path:
    if path_text:
        p = Path(path_text)
        if p.exists():
            return p
    for p in candidates:
        if p.exists():
            return p
    checked = "\n".join(str(p) for p in candidates)
    raise FileNotFoundError(f"Required Grok path not found. Checked:\n{checked}")


def _find_newest_mp4(sessions_dir: Path, since_ts: float) -> Path | None:
    candidates: list[Path] = []
    if not sessions_dir.exists():
        return None
    for p in sessions_dir.rglob("*.mp4"):
        try:
            st = p.stat()
            if st.st_mtime >= since_ts and st.st_size > 100_000:
                candidates.append(p)
        except OSError:
            continue
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.stat().st_mtime)


def _wait_stable(path: Path, timeout_sec: int = 90) -> bool:
    deadline = time.time() + timeout_sec
    last_size = -1
    stable_count = 0
    while time.time() < deadline:
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        if size > 100_000 and size == last_size:
            stable_count += 1
            if stable_count >= 3:
                return True
        else:
            stable_count = 0
        last_size = size
        time.sleep(1.5)
    return False


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate one Page5 health infographic video with Grok CLI.")
    ap.add_argument("--prompt-file", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--stem", default="page5_health")
    ap.add_argument("--max-seconds", type=int, default=720)
    ap.add_argument("--grok-exe", default="")
    ap.add_argument("--sessions-dir", default="")
    args = ap.parse_args()

    prompt_file = Path(args.prompt_file)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    done_path = output_dir / "grok_video.done.json"
    if done_path.exists():
        done_path.unlink()
    if not prompt_file.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_file}")

    grok_exe = _resolve_existing(args.grok_exe, _candidate_paths())
    sessions_dir = _resolve_existing(args.sessions_dir, _candidate_sessions())
    prompt = prompt_file.read_text(encoding="utf-8-sig").strip()
    if not prompt:
        raise RuntimeError("Prompt file is empty.")

    started = time.time()
    proc = subprocess.Popen(
        [str(grok_exe), "-p", prompt],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    found: Path | None = None
    proc_out = ""
    proc_err = ""
    deadline = started + max(120, int(args.max_seconds))
    while time.time() < deadline:
        candidate = _find_newest_mp4(sessions_dir, started - 1.0)
        if candidate and _wait_stable(candidate):
            found = candidate
            break
        if proc.poll() is not None:
            try:
                out, err = proc.communicate(timeout=2)
                proc_out = (out or "").strip()
                proc_err = (err or "").strip()
            except Exception:
                pass
            # Grok sometimes writes media after text returns, so keep polling.
        time.sleep(2.0)

    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

    if found is None:
        raise RuntimeError(
            "Grok CLI did not produce a new MP4 for Page5.\n"
            f"STDOUT:\n{proc_out[:1500]}\nSTDERR:\n{proc_err[:1500]}"
        )

    output_mp4 = output_dir / f"{args.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_raw.mp4"
    # WSL can fail copying Windows file timestamps from Grok's session folder.
    # Copy bytes only; the run manifest records fresh metadata separately.
    shutil.copyfile(found, output_mp4)
    payload = {
        "status": "ok",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_mp4": str(found),
        "output_mp4": str(output_mp4),
        "prompt_file": str(prompt_file),
        "grok_exe": str(grok_exe),
        "sessions_dir": str(sessions_dir),
    }
    done_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OUTPUT_MP4={output_mp4}")
    print(f"DONE={done_path}")


if __name__ == "__main__":
    main()
