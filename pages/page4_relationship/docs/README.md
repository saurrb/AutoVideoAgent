# Page 4 Relationship (Redesigned)

This page is rebuilt with a staged pipeline architecture and uses shared tools from:
`C:\Users\Saurabh\Documents\AutoVideoAgent\pages\automation_tools`

## Archived old implementation
Previous implementation is archived at:
`C:\Users\Saurabh\Documents\AutoVideoAgent\pages\page4_relationship_old_20260602_003021`

## New architecture
1. Stage 1 (`prepare`):
   - Generate narration/caption/hashtags
   - Generate Speechma voice
   - Build scene prompt text/json
2. Stage 2 (`generate`):
   - Generate scene images via Grok CLI tool
3. Stage 3 (`render`):
   - Single-pass final render
4. Stage outputs:
   - `state/01_prepare.json`
   - `state/02_generate.json`
   - `state/03_render.json`
   - final manifest `page4_<id>.manifest.json`

## Main entry
`python C:\Users\Saurabh\Documents\AutoVideoAgent\pages\page4_relationship\scripts\page4_pipeline.py`

## Compatibility
Global scheduler/job-runner still calls:
`python C:\Users\Saurabh\Documents\AutoVideoAgent\scripts\generate_page4_reel.py`

That wrapper now delegates to the new pipeline.
