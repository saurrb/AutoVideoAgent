# Quick Command: Create + Post Reel

Use one command from project root:

`reel_post.cmd <page_name>`

Example:

`reel_post.cmd female_psychology`

What it does:
- Renders next reel batch using your existing page config.
- Creates one caption (single paragraph) plus 7 hashtags.
- Posts reel to Facebook using `secrets/meta_config.json`.
- Saves caption text next to manifest as `*.caption.txt`.

Dry run (no posting):

`python .\scripts\create_and_post_reel.py --page female_psychology --dry-run`

