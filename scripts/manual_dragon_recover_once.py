import json
from datetime import datetime
from pathlib import Path
import importlib.util
import sys

ROOT = Path(r"C:\Users\Saurabh\Documents\AutoVideoAgent")
mod_path = ROOT / "scripts" / "daily_ui_batch_schedule.py"
spec = importlib.util.spec_from_file_location("daily_ui_batch_schedule", mod_path)
mod = importlib.util.module_from_spec(spec)
sys.modules["daily_ui_batch_schedule"] = mod
spec.loader.exec_module(mod)

plans = mod._load_plans()
plan = [p for p in plans if p.page_key == "dragon_cinema"][0]

items = [
    {
        "slot": "17:00",
        "video": r"C:\Users\Saurabh\Documents\AutoVideoAgent\runs\2026-05-30\dragon_cinema\20260530_110552\dragon_43_final_20s_720x1280.mp4",
        "caption": "",
        "hashtags": "",
    },
    {
        "slot": "15:00",
        "video": r"C:\Users\Saurabh\Documents\AutoVideoAgent\runs\2026-05-30\dragon_cinema\20260530_112059\dragon_44_final_20s_720x1280.mp4",
        "caption": "",
        "hashtags": "",
    },
    {
        "slot": "09:00",
        "video": r"C:\Users\Saurabh\Documents\AutoVideoAgent\runs\2026-05-30\dragon_cinema\20260530_120340\dragon_47_final_20s_720x1280.mp4",
        "caption": "",
        "hashtags": "",
    },
]

# Pull captions/hashtags from DB by item id inferred from filename dragon_<id>_
import re, sqlite3
con = sqlite3.connect(ROOT / "data" / "v2" / "state.sqlite3")
for it in items:
    m = re.search(r"dragon_(\d+)_", Path(it["video"]).name)
    cid = int(m.group(1)) if m else None
    row = con.execute("select caption, hashtags from content_bank_rows where page_key='dragon_cinema' and item_id=?", (cid,)).fetchone()
    cap = (row[0] or "").strip() if row else ""
    h = (row[1] or "").strip() if row else ""
    it["caption"] = (cap + "\n\n" + h).strip()

run_stamp = datetime.now().strftime("manual_recover_%Y%m%d_%H%M%S")
run_dir = ROOT / "runs" / "daily_batch" / run_stamp
shot_dir = run_dir / "screens"
run_dir.mkdir(parents=True, exist_ok=True)
shot_dir.mkdir(parents=True, exist_ok=True)

results = []
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9100", timeout=120000)
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    now = datetime.now()
    for it in items:
        hh,mm = map(int,it["slot"].split(":"))
        target = datetime(now.year, now.month, now.day, hh, mm)
        if target <= now:
            from datetime import timedelta
            target = target + timedelta(days=1)
        status = mod._upload_and_schedule_with_retry(ctx, plan, it["video"], it["caption"], target, shot_dir)
        results.append({"slot": it["slot"], "video": it["video"], "target": target.isoformat(timespec="minutes"), "status": status})

out = run_dir / "manual_recover_report.json"
out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print(str(out))
for r in results:
    print(r["slot"], r["status"].get("ok"), r["target"])
