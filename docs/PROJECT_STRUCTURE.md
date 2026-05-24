# Project Structure (Scalable Multi-Page)

## Code
- `src/autovideo/`: V2 pipeline code (domain, services, CLI).
- `tools/`: runnable launchers (for example `render_v2.cmd`).
- `scripts/`: utility scripts and legacy-compatible helpers.

## Config
- `configs/presets/`: reusable style presets.
- `configs/pages/`: page profiles (one YAML per page).

## Per-Page Workspace
- `pages/<page_key>/content/`: Excel/line-bank for that page.
- `pages/<page_key>/assets/logo/`: logo assets for that page.
- `pages/<page_key>/assets/music/`: music for that page.
- `pages/<page_key>/assets/backgrounds/`: page background videos/images.
- `pages/<page_key>/docs/`: page-specific notes/SOP.
- `pages/<page_key>/outputs/`: optional page-local exports.

## Runtime Data
- `pages/<page_key>/data/state.sqlite3`: page-scoped V2 state DB.
- `runs/YYYY-MM-DD/<page_key>/<run_id>/`: generated outputs + manifest.

## Archive
- `archive/packages/`: large package/backup zips.
- `archive/unused/`: old or inactive files.

## Add a New Page
1. Create `pages/<new_page_key>/...` folders following `female_psychology`.
2. Copy and edit `configs/pages/female_psychology.yaml` to `configs/pages/<new_page_key>.yaml`.
3. Point config paths to that page's `content` and `assets`.
4. Run:
   - `tools\\render_v2.cmd --page <new_page_key>`

