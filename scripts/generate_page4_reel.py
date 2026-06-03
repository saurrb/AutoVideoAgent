from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str]) -> str:
    p = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\nSTDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}")
    return p.stdout or ""


def _parse_key(stdout: str, key: str) -> str:
    prefix = f"{key}="
    for line in stdout.splitlines():
        if line.startswith(prefix):
            return line.split("=", 1)[1].strip()
    raise RuntimeError(f"Missing {key}=... in output:\n{stdout}")


def main() -> None:
    out = _run([sys.executable, str(PROJECT_ROOT / "pages" / "page4_relationship" / "scripts" / "page4_pipeline.py")])
    manifest_path = Path(_parse_key(out, "MANIFEST"))
    video_path = Path(_parse_key(out, "VIDEO"))
    print(f"MANIFEST={manifest_path}")
    print(f"VIDEO={video_path}")


if __name__ == "__main__":
    main()
