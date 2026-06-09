Dragon Cinema Page

Purpose
- No text-overlay reels.
- 20s final reel built as 10s scene A + 10s scene B continuation.
- Grok CLI does not reliably read the previous video/image, so Scene B uses written continuity details instead of a last-frame reference.

Content Source
- AI-generated at run time by Grok text generation.
- The Excel file is retained only as historical/reference content.

Airflow Steps
- generate_dragon_package
- scene_a_generate
- scene_b_generate
- final_render
- upload_schedule
- telegram_notify

Generation Rules
- No narration.
- No text overlay.
- Two Grok CLI videos, about 10 seconds each.
- Scene B directly continues Scene A using repeated dragon/world continuity details.
- Final FFmpeg render normalizes to 720x1280, preserves audio, and overlays the page logo.

