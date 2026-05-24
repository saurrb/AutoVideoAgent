# Meta API Setup For Female psychology Page

Target page:
- `https://www.facebook.com/profile.php?id=61590452875190`
- Page ID: `61590452875190`

## Prerequisites

- Meta app with Facebook Login configured.
- OAuth redirect URI added in Meta app:
  - `http://localhost:8766/`
- Required permissions at minimum:
  - `pages_show_list`
  - `pages_read_engagement`
  - `pages_manage_posts`
  - `pages_manage_metadata`
  - `business_management`

## One-command setup and check

PowerShell:

```powershell
$env:META_APP_ID = "<YOUR_META_APP_ID>"
$env:META_APP_SECRET = "<YOUR_META_APP_SECRET>"
powershell -ExecutionPolicy Bypass -File .\scripts\meta_setup_and_check.ps1 -PageId "61590452875190"
```

This runs:
1. OAuth and token save to `secrets/meta_token.json`
2. API check and page config save to `secrets/meta_config.json`

## What is validated

`scripts/meta_api_check.py` now validates:
- user token works
- page is discoverable in `me/accounts`
- granted permissions are captured
- page tasks are captured
- `/{page_id}/video_reels` edge access probe result is captured

The output config includes:
- `granted_user_permissions`
- `page_tasks`
- `can_access_video_reels_edge`
- `video_reels_probe_error` (if any)

## Next step after check

If the check passes, use local reel publishing (from old flow ported into current project next):
- upload local MP4 to page reels via Graph API
- poll processing and publish status

