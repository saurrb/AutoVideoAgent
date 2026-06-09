from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

from dragon_step_common import resolve_grok_paths, run_grok_and_wait_for_mp4, write_done_json


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--context", required=True)
    ap.add_argument("--in-a", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    started = time.time()
    ctx = json.loads(Path(args.context).read_text(encoding="utf-8"))
    root = Path(ctx["project_root"])
    grok, grok_home = resolve_grok_paths(root)
    run_dir = Path(ctx["run_dir"])

    prompt = (
        f"Generate one video as a direct continuation of scene A using only the written continuity details in this prompt. "
        f"Duration {ctx['scene_b_duration_sec']} seconds. "
        f"Resolution {ctx['target_resolution']}. Aspect ratio {ctx['target_aspect_ratio']}. "
        f"Prompt: {ctx['scene_b_prompt']} Return only the generated video file path."
    )
    src = run_grok_and_wait_for_mp4(grok, prompt, cwd=root, home=grok_home, poll_sec=3.0, max_wait_sec=0)
    out_mp4 = run_dir / f"dragon_{ctx['row_id']}_scene_b.mp4"
    out_mp4.write_bytes(src.read_bytes())

    done = {
        "step": "scene_b",
        "status": "ok",
        "row_id": ctx["row_id"],
        "last_frame": "",
        "output_mp4": str(out_mp4),
        "seconds": round(time.time() - started, 2),
        "timestamp": datetime.utcnow().isoformat(),
    }
    write_done_json(Path(args.out), done)


if __name__ == "__main__":
    main()
