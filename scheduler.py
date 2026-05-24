from __future__ import annotations

import os
import time

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import load_settings
from app.db import get_conn, init_db
from app.lines import seed_lines
from app.pipeline import run_once


def main() -> None:
    settings = load_settings()
    conn = get_conn(settings.db_file)
    init_db(conn)
    seed_lines(conn, settings.lines_file)
    interval_hours = int(os.environ.get("POST_INTERVAL_HOURS", "2"))

    def job() -> None:
        out = run_once(conn, settings)
        print(f"POST_OK={out}", flush=True)

    scheduler = BackgroundScheduler()
    scheduler.add_job(job, "interval", hours=interval_hours, next_run_time=None)
    scheduler.start()
    print(f"SCHEDULER_STARTED interval_hours={interval_hours}", flush=True)
    try:
        while True:
            time.sleep(30)
    except KeyboardInterrupt:
        scheduler.shutdown()


if __name__ == "__main__":
    main()
