from __future__ import annotations

from app.config import load_settings
from app.db import get_conn, init_db
from app.lines import seed_lines
from app.pipeline import run_once


def main() -> None:
    settings = load_settings()
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    conn = get_conn(settings.db_file)
    init_db(conn)
    seed_lines(conn, settings.lines_file)
    out = run_once(conn, settings)
    print(f"REEL_CREATED={out}")


if __name__ == "__main__":
    main()
