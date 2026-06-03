from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def main() -> None:
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "reload_page_content_to_db.py"),
        "--page",
        "female_psychology",
        "--xlsx",
        str(HERE / "reel_content_bank.xlsx"),
        "--sheet",
        "Sheet1",
    ]
    # Add --reset-used if you want to reset all used flags.
    proc = subprocess.run(cmd, cwd=ROOT)
    raise SystemExit(proc.returncode)


if __name__ == "__main__":
    main()
