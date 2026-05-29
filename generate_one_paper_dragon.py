#!/usr/bin/env python3
"""Generate one 10s 9:16 720p video using local Grok CLI for the paper dragon prompt.
Prints progress and finally the video file path (only path on last line for easy capture).
"""
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
HOME = Path.home()
GROK_EXE = HOME / ".grok" / "bin" / "grok.exe"
SESSIONS_DIR = HOME / ".grok" / "sessions"

PROMPT = (
    "Generate one video. Duration 10 seconds. Resolution 720p. Aspect ratio 9:16. "
    "Prompt: Deep in a forgotten library dimension, a paper dragon with delicate origami-like scales guards forbidden knowledge. "
    "Return only the generated video file path."
)

def find_newest_mp4(since_ts: float):
    if not SESSIONS_DIR.exists():
        return None
    candidates = []
    for p in SESSIONS_DIR.rglob("*.mp4"):
        try:
            if p.stat().st_mtime > since_ts and p.stat().st_size > 100000:
                candidates.append(p)
        except Exception:
            pass
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)

def wait_stable(path: Path, checks: int = 3, interval: float = 1.5):
    last = -1
    stable = 0
    for _ in range(20):  # max ~30s wait
        try:
            size = path.stat().st_size if path.exists() else 0
        except Exception:
            size = 0
        if size > 100000 and size == last:
            stable += 1
            if stable >= checks:
                return True
        else:
            stable = 0
        last = size
        time.sleep(interval)
    return False

def main():
    if not GROK_EXE.exists():
        print(f"ERROR: Grok CLI not found at {GROK_EXE}", file=sys.stderr)
        sys.exit(1)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = PROJECT_ROOT / "runs" / "manual_one_video" / ts
    run_dir.mkdir(parents=True, exist_ok=True)

    (run_dir / "prompt.txt").write_text(PROMPT, encoding="utf-8")

    print(f"RUN_DIR={run_dir}", flush=True)
    print(f"Starting grok video generation for paper dragon (10s 9:16 720p)...", flush=True)
    print(f"Prompt length: {len(PROMPT)} chars", flush=True)
    start_ts = time.time()

    proc = subprocess.Popen(
        [str(GROK_EXE), "-p", PROMPT],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    result_path = None
    try:
        while True:
            # Prefer fs detection (reliable like project scripts)
            newest = find_newest_mp4(start_ts - 1.0)
            if newest is not None:
                print(f"Detected new mp4 candidate: {newest}", flush=True)
                if wait_stable(newest):
                    result_path = newest
                    print(f"File stable at size {newest.stat().st_size}", flush=True)
                    # Try to terminate grok now that we have the file
                    try:
                        if proc.poll() is None:
                            proc.terminate()
                    except Exception:
                        pass
                    break

            # Check if grok process ended
            if proc.poll() is not None:
                out, err = proc.communicate(timeout=10)
                print("Grok process exited.", flush=True)
                if out and out.strip():
                    print(f"STDOUT: {out.strip()[:500]}", flush=True)
                    # If it printed a clean path, use it
                    line = out.strip().splitlines()[-1] if out.strip() else ""
                    if line.lower().endswith(".mp4") and "grok" in line.lower():
                        p = Path(line)
                        if p.exists():
                            result_path = p
                            break
                if err:
                    print(f"STDERR: {err[:500]}", flush=True)
                if result_path is None:
                    # last chance: find any very recent mp4
                    result_path = find_newest_mp4(start_ts - 5.0)
                break

            elapsed = int(time.time() - start_ts)
            if elapsed > 0 and elapsed % 10 == 0:
                print(f"  polling... elapsed {elapsed}s", flush=True)

            if elapsed > 900:  # 15min hard cap
                print("Timeout after 15min", flush=True)
                try:
                    proc.kill()
                except Exception:
                    pass
                break

            time.sleep(3.0)
    finally:
        try:
            if proc.poll() is None:
                proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            pass

    if not result_path:
        # final fallback scan
        result_path = find_newest_mp4(start_ts - 1.0)

    if result_path and result_path.exists():
        # Copy to run dir for convenience
        local_copy = run_dir / "paper_dragon_10s_9x16_720p.mp4"
        try:
            local_copy.write_bytes(result_path.read_bytes())
            print(f"Copied video to local: {local_copy}", flush=True)
        except Exception as e:
            print(f"Copy warning: {e}", flush=True)

        (run_dir / "video_path.txt").write_text(str(result_path), encoding="utf-8")

        # Print ONLY the path as last line (per user request style)
        print(str(result_path), flush=True)
        print(f"SUCCESS: {result_path}", file=sys.stderr)
        sys.exit(0)
    else:
        print("ERROR: No video file was produced.", file=sys.stderr)
        # Try to show last grok output if any
        try:
            if proc.stdout:
                remaining_out = proc.stdout.read()
                if remaining_out:
                    print(f"final stdout: {remaining_out[:300]}", file=sys.stderr)
        except Exception:
            pass
        sys.exit(1)

if __name__ == "__main__":
    main()
