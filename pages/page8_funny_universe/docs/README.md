# Page 8 Funny Universe

Animated 10-second vertical cartoon comics for the Facebook page Funny Universe.

Pipeline:
1. Rotate through one locked character from `data/characters.json`.
2. Grok text creates a short joke plan, flexible beat timing, optional speech bubbles, optional meme music/SFX cues, caption, hashtags, and a video prompt.
3. Grok video creates one 10-second 9:16 animated cartoon MP4.
4. FFmpeg normalizes the output to 720x1280, overlays the Page 8 logo in the lower-right corner, and mixes any selected music/SFX cues at the exact seconds returned by Grok.
5. Airflow can schedule/upload through the Meta UI uploader; manual sample tests stop before upload.

Page asset id:

```text
1200269989829997
```

Character rotation:

The 15 locked characters rotate one at a time. Supporting characters are allowed, but exactly one locked character is featured in each run.

Music/SFX:

`assets/music/music_metadata.json` catalogs the meme audio files with duration, category, and best-use notes. Grok receives this catalog during content generation and can choose 0 to 3 cues with `start_sec` and `volume`; no fixed timing template is enforced.

Logo:

`assets/logo/logo1.png` is rendered at 116px wide in the lower-right corner with 28px right/bottom margins.
