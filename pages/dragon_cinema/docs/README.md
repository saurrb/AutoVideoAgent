Dragon Cinema Page

Purpose
- No text-overlay reels.
- 20s final reel built as 10s scene A + 10s scene B continuation.
- Scene B uses the last frame of scene A as continuity reference.

Content Source
- Excel: pages/dragon_cinema/content/dragon_scenes.xlsx
- Sheet: Sheet1

Columns
- id
- heading
- scene_a_prompt
- scene_b_prompt
- scene_duration_sec
- target_resolution
- target_aspect_ratio
- used
- notes

Scale Plan
- Keep first 5 rows as quality seed.
- Expand to 10,000 rows in batches (e.g., 250 rows x 40 batches).
- Used rows are tracked in pages/dragon_cinema/data/used_rows.json so the Excel structure stays unchanged.
