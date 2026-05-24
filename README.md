# AutoVideoAgent (Minimal FB Reels Pipeline)

This project does:
1. picks 5 unused lines from your line bank
2. renders a black 9:16 reel with white text + background music
3. posts to Facebook Page Reels via Graph API
4. tracks used lines and posted reels in SQLite

## 1) Setup

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

## 2) Prepare inputs

1. Put your 10,000 lines in `pages\female_psychology\content\lines.txt` (one line per row).
2. Put royalty-free music at `assets\music\bg.mp3`.
3. Copy `.env.example` to `.env` (auto-copied by setup) and adjust paths if needed.

## 3) Meta token/config reuse from old project flow

```powershell
.\.venv\Scripts\python.exe .\scripts\meta_oauth.py --app-id <APP_ID> --app-secret <APP_SECRET> --token-out .\config\token.json
.\.venv\Scripts\python.exe .\scripts\meta_api_check.py --token .\config\token.json --save-config .\config\meta_config.json --page-id <OPTIONAL_PAGE_ID>
```

## 4) Run once

```powershell
.\.venv\Scripts\python.exe .\main.py
```

## 5) Run every 2 hours

```powershell
.\.venv\Scripts\python.exe .\scheduler.py
```

Keep this process running on your spare laptop.

## SQLite

Page-scoped state lives at:
- `pages\<page_key>\data\state.sqlite3` (example: `pages\female_psychology\data\state.sqlite3`)

V2 tracking tables include:
- `content_items`: row usage by `page_key`
- `render_jobs`: render job/output history

