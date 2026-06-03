from __future__ import annotations

import json
import re
import subprocess
import sys
import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import time
import hashlib

from playwright.sync_api import sync_playwright


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_LOG_DIR = PROJECT_ROOT / "runs" / "daily_batch"


def _retry_ui(action_name: str, fn, *, max_attempts: int = 4, base_delay: float = 0.5, shot_dir: Path | None = None, page_key: str = ""):
    last_ex = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception as ex:
            last_ex = ex
            if shot_dir is not None:
                # caller can pass page via closure if needed; best-effort screenshot done outside
                pass
            if attempt >= max_attempts:
                break
            time.sleep(base_delay * (2 ** (attempt - 1)))
    raise RuntimeError(f"UI action failed: {action_name}; last_error={last_ex}")


def _wait_until(predicate, *, timeout_sec: float = 30.0, poll_sec: float = 0.4) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            if predicate():
                return True
        except Exception:
            pass
        time.sleep(poll_sec)
    return False


@dataclass
class PagePlan:
    page_key: str
    asset_id: str
    generator_type: str
    slots: list[str]  # HH:MM

def _load_plans() -> list[PagePlan]:
    runtime_json = PROJECT_ROOT / "control" / "automation_runtime.json"
    if not runtime_json.exists():
        raise RuntimeError(
            f"Missing runtime control file: {runtime_json}. Run scripts/sync_automation_control.py first."
        )
    cfg = json.loads(runtime_json.read_text(encoding="utf-8-sig"))
    plans: list[PagePlan] = []
    for p in cfg.get("pages", []):
        if not bool(p.get("enabled", True)):
            continue
        page_key = str(p.get("page_key", "")).strip()
        asset_id = str(p.get("facebook_asset_id", "")).strip()
        slots = list(p.get("posting_slots", []))
        if not page_key or not asset_id or not slots:
            continue
        plans.append(
            PagePlan(
                page_key=page_key,
                asset_id=asset_id,
                generator_type=str(p.get("generator_type", "")).strip(),
                slots=slots,
            )
        )
    if not plans:
        raise RuntimeError("No enabled plans found in control/automation_runtime.json")
    return plans


def _parse_manifest_from_stdout(stdout: str) -> Path:
    for line in stdout.splitlines():
        if line.startswith("MANIFEST="):
            return Path(line.split("=", 1)[1].strip())
    raise RuntimeError(f"Could not parse MANIFEST path from output:\n{stdout}")


def _generate_reel(plan: PagePlan) -> tuple[Path, str, str]:
    if plan.generator_type == "dragon_chain" or plan.page_key == "dragon_cinema":
        cmd = [sys.executable, str(PROJECT_ROOT / "scripts" / "generate_dragon_chain_reel.py"), "--page", plan.page_key]
        proc = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"Reel generation failed for {plan.page_key}:\n{proc.stdout}\n{proc.stderr}")
        manifest_path = _parse_manifest_from_stdout(proc.stdout)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        video = str(Path(manifest["final_mp4"]).resolve())
        caption = str(manifest.get("caption", "")).strip()
        hashtags = str(manifest.get("hashtags", "")).strip()
        merged_caption = f"{caption}\n\n{hashtags}".strip() if (caption or hashtags) else ""
        return manifest_path, video, merged_caption
    if plan.generator_type == "page4_pipeline" or plan.page_key == "page4_relationship":
        cmd = [sys.executable, str(PROJECT_ROOT / "scripts" / "generate_page4_reel.py")]
        proc = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"Reel generation failed for {plan.page_key}:\n{proc.stdout}\n{proc.stderr}")
        manifest_path = _parse_manifest_from_stdout(proc.stdout)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        video = str(Path(manifest["output_mp4"]).resolve())
        caption = str(manifest.get("caption", "")).strip()
        return manifest_path, video, caption

    cmd = [sys.executable, str(PROJECT_ROOT / "scripts" / "create_and_post_reel.py"), "--page", plan.page_key, "--dry-run"]
    proc = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Reel generation failed for {plan.page_key}:\n{proc.stdout}\n{proc.stderr}")
    manifest_path = _parse_manifest_from_stdout(proc.stdout)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    video = str(Path(manifest["output_mp4"]).resolve())
    caption_file = manifest_path.with_suffix(".caption.txt")
    caption = caption_file.read_text(encoding="utf-8").strip() if caption_file.exists() else ""
    return manifest_path, video, caption


def _schedule_dt_for_slot(slot_hhmm: str, now: datetime) -> datetime:
    hh, mm = [int(x) for x in slot_hhmm.split(":")]
    # New policy: every batch run schedules reels for next day only.
    base = now + timedelta(days=1)
    dt = base.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return dt


def _set_story_toggle_on(page) -> bool:
    # Find the row that contains "Facebook story" and ensure its switch is ON.
    row = page.locator("div").filter(has_text=re.compile(r"Facebook story", re.I)).first
    if row.count() == 0:
        return False
    sw = row.locator("button[role='switch'], [aria-checked='true'], [aria-checked='false']").first
    if sw.count() == 0:
        return False
    aria = (sw.get_attribute("aria-checked") or "").lower().strip()
    if aria == "false":
        sw.click(timeout=5000)
        return True
    return aria == "true"


def _fill_caption_on_page(page, caption: str) -> bool:
    if not caption.strip():
        return False
    # Meta variants expose different editors/textarea fields. Try broadly.
    targets = [
        page.locator("textarea").first,
        page.locator("div[role='textbox']").first,
        page.locator("[contenteditable='true']").first,
    ]
    for t in targets:
        try:
            if t.count() == 0:
                continue
            t.click(timeout=5000)
            # Prefer paste-style single-shot insertion for stability with long text/hashtags.
            try:
                page.keyboard.press("Control+A")
                page.keyboard.press("Backspace")
                page.keyboard.insert_text(caption)
            except Exception:
                # fallback: fill() works on textarea/input
                try:
                    t.fill(caption)
                except Exception:
                    # last fallback: typed path
                    page.keyboard.press("Control+A")
                    page.keyboard.type(caption)
            # Verify caption text is present somewhere on page.
            if _wait_until(lambda: caption[:20].lower() in page.locator("body").inner_text().lower(), timeout_sec=5):
                return True
        except Exception:
            continue
    return False


def _fill_schedule_time(page, target: datetime, shot_dir: Path, page_key: str) -> None:
    # Click Schedule option first (inside scheduling options card, not footer action button).
    page.locator("div").filter(has_text=re.compile(r"Scheduling options", re.I)).get_by_role(
        "button", name=re.compile(r"^Schedule$", re.I)
    ).first.click(timeout=10000)
    _wait_until(lambda: page.locator("input:visible").count() > 0 or page.get_by_text(re.compile(r"^\d{1,2}\s+[A-Za-z]{3}\s+\d{4}$")).count() > 0, timeout_sec=8)

    # Preferred stable input style for this account/UI:
    # date as D/M/YYYY and time as HH then ArrowRight then MM (24h).
    date_text = f"{target.day}/{target.month}/{target.year}"
    hour_text = target.strftime("%H")
    minute_text = target.strftime("%M")

    def _fill_row_by_label(label_regex: str) -> bool:
        try:
            lbl = page.get_by_text(re.compile(label_regex, re.I)).first
            if lbl.count() == 0:
                return False
            # On Meta schedule card, date/time inputs are typically the first two visible
            # inputs after the network label node.
            d = lbl.locator("xpath=following::input[1]").first
            t = lbl.locator("xpath=following::input[2]").first
            if d.count() > 0 and t.count() > 0:
                d.click(timeout=4000)
                page.keyboard.press("Control+A")
                page.keyboard.type(date_text)
                t.click(timeout=4000)
                page.keyboard.press("Control+A")
                page.keyboard.type(hour_text)
                page.keyboard.press("ArrowRight")
                page.keyboard.type(minute_text)
                return True
        except Exception:
            return False
        return False

    # First try explicit per-network rows when present (Facebook always, Instagram optional).
    filled_explicit = False
    if _fill_row_by_label(r"^Facebook$"):
        filled_explicit = True
    # Instagram row appears only on some pages; fill only if present.
    if _fill_row_by_label(r"^Instagram$"):
        filled_explicit = True
    if filled_explicit:
        _wait_until(lambda: True, timeout_sec=0.5, poll_sec=0.5)
        page.screenshot(path=str(shot_dir / f"{page_key}_05a_date_filled.png"), full_page=True)
        page.screenshot(path=str(shot_dir / f"{page_key}_05b_time_filled.png"), full_page=True)
        return

    # Preferred on newer Meta variants: fill every visible schedule row (Facebook + Instagram)
    # by targeting all date-like inputs in the scheduling card.
    visible_inputs = page.locator("input:visible")
    date_like_inputs = []
    for i in range(visible_inputs.count()):
        inp = visible_inputs.nth(i)
        try:
            val = (inp.get_attribute("value") or "").strip()
            ph = (inp.get_attribute("placeholder") or "").strip()
            aria = (inp.get_attribute("aria-label") or "").strip().lower()
            blob = f"{val} {ph} {aria}".lower()
            if ("date" in blob) or re.search(r"\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}", blob):
                date_like_inputs.append(inp)
        except Exception:
            continue
    if date_like_inputs:
        filled = 0
        for inp in date_like_inputs:
            try:
                inp.click(timeout=5000)
                page.keyboard.press("Control+A")
                page.keyboard.type(date_text)
                page.keyboard.press("Tab")
                page.keyboard.press("Control+A")
                page.keyboard.type(hour_text)
                page.keyboard.press("ArrowRight")
                page.keyboard.type(minute_text)
                filled += 1
            except Exception:
                continue
        if filled > 0:
            _wait_until(lambda: True, timeout_sec=0.5, poll_sec=0.5)
            page.screenshot(path=str(shot_dir / f"{page_key}_05a_date_filled.png"), full_page=True)
            page.screenshot(path=str(shot_dir / f"{page_key}_05b_time_filled.png"), full_page=True)
            return

    date_input = page.locator(
        "input[aria-label*='date' i], input[placeholder*='date' i], input[name*='date' i]"
    ).first
    hours_input = page.locator("input[aria-label='hours' i], input[name='hours' i]").first
    minutes_input = page.locator("input[aria-label='minutes' i], input[name='minutes' i]").first

    # Fallbacks for UIs where labels are not present: infer from visible input order/patterns.
    if date_input.count() == 0 or hours_input.count() == 0 or minutes_input.count() == 0:
        visible_inputs = page.locator("input:visible")
        date_candidate = None
        hours_candidate = None
        minutes_candidate = None
        for i in range(visible_inputs.count()):
            inp = visible_inputs.nth(i)
            val = (inp.get_attribute("value") or "").strip()
            ph = (inp.get_attribute("placeholder") or "").strip()
            aria = (inp.get_attribute("aria-label") or "").strip().lower()
            blob = f"{val} {ph}".lower()
            if date_candidate is None and (re.search(r"\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}", blob) or "dd" in blob):
                date_candidate = inp
            if hours_candidate is None and ("hours" in aria or ph.lower() == "hours"):
                hours_candidate = inp
            if minutes_candidate is None and ("minutes" in aria or ph.lower() == "minutes"):
                minutes_candidate = inp
        if date_input.count() == 0 and date_candidate is not None:
            date_input = date_candidate
        if hours_input.count() == 0 and hours_candidate is not None:
            hours_input = hours_candidate
        if minutes_input.count() == 0 and minutes_candidate is not None:
            minutes_input = minutes_candidate

    # Meta reels UI variant: date/time appear as text chips in one schedule row.
    if date_input.count() == 0:
        date_chip = page.get_by_text(re.compile(r"^\d{1,2}\s+[A-Za-z]{3}\s+\d{4}$")).first
        if date_chip.count() > 0:
            date_chip.click(timeout=5000)
            page.keyboard.press("Control+A")
            page.keyboard.type(date_text)
            _wait_until(lambda: True, timeout_sec=0.5, poll_sec=0.5)
            page.screenshot(path=str(shot_dir / f"{page_key}_05a_date_filled.png"), full_page=True)
            # Continue to standard hour/minute fill below if available.

    if date_input.count() == 0:
        # Last-resort keyboard path: type into first focused schedule field then tab to time.
        page.keyboard.press("Control+A")
        page.keyboard.type(date_text)
        page.keyboard.press("Tab")
        page.keyboard.press("Control+A")
        page.keyboard.type(hour_text)
        page.keyboard.press("ArrowRight")
        page.keyboard.type(minute_text)
        _wait_until(lambda: True, timeout_sec=0.5, poll_sec=0.5)
        page.screenshot(path=str(shot_dir / f"{page_key}_05a_date_filled.png"), full_page=True)
        page.screenshot(path=str(shot_dir / f"{page_key}_05b_time_filled.png"), full_page=True)
        return
    if hours_input.count() == 0 or minutes_input.count() == 0:
        # If date exists but separate time fields aren't detectable, tab fallback.
        date_input.click(timeout=5000)
        page.keyboard.press("Control+A")
        page.keyboard.type(date_text)
        page.keyboard.press("Tab")
        page.keyboard.press("Control+A")
        page.keyboard.type(hour_text)
        page.keyboard.press("ArrowRight")
        page.keyboard.type(minute_text)
        _wait_until(lambda: True, timeout_sec=0.5, poll_sec=0.5)
        page.screenshot(path=str(shot_dir / f"{page_key}_05a_date_filled.png"), full_page=True)
        page.screenshot(path=str(shot_dir / f"{page_key}_05b_time_filled.png"), full_page=True)
        return

    date_input.click(timeout=5000)
    page.keyboard.press("Control+A")
    page.keyboard.type(date_text)
    _wait_until(lambda: True, timeout_sec=0.5, poll_sec=0.5)
    page.screenshot(path=str(shot_dir / f"{page_key}_05a_date_filled.png"), full_page=True)

    hours_input.click(timeout=5000)
    page.keyboard.press("Control+A")
    page.keyboard.type(hour_text)
    page.keyboard.press("ArrowRight")
    minutes_input.click(timeout=5000)
    page.keyboard.press("Control+A")
    page.keyboard.type(minute_text)
    _wait_until(lambda: True, timeout_sec=0.5, poll_sec=0.5)
    page.screenshot(path=str(shot_dir / f"{page_key}_05b_time_filled.png"), full_page=True)


def _upload_and_schedule(page, plan: PagePlan, video_path: str, caption: str, when_dt: datetime, shot_dir: Path) -> dict:
    if "business.facebook.com" not in page.url and page.url:
        # session drift signal; reset to fresh composer context
        page.goto("about:blank")

    page.goto(
        f"https://business.facebook.com/latest/home?asset_id={plan.asset_id}",
        wait_until="domcontentloaded",
        timeout=120000,
    )
    _wait_until(lambda: page.get_by_role("button", name="Create Reel").count() > 0, timeout_sec=12)
    page.screenshot(path=str(shot_dir / f"{plan.page_key}_01_home.png"), full_page=True)

    _retry_ui("click_create_reel", lambda: page.get_by_role("button", name="Create Reel").click(timeout=20000), shot_dir=shot_dir, page_key=plan.page_key)
    _wait_until(lambda: page.get_by_role("button", name="Add video").count() > 0, timeout_sec=20)
    page.screenshot(path=str(shot_dir / f"{plan.page_key}_02_composer.png"), full_page=True)

    upload_ok = False
    upload_err = ""
    try:
        with page.expect_file_chooser(timeout=30000) as fc:
            _retry_ui("click_add_video", lambda: page.get_by_role("button", name="Add video").click(), shot_dir=shot_dir, page_key=plan.page_key)
        # Some Meta variants need longer to bind chooser->input.
        fc.value.set_files(video_path, timeout=90000)
        upload_ok = True
    except Exception as ex:
        upload_err = f"{type(ex).__name__}: {ex}"
    if not upload_ok:
        # Fallback for flaky chooser: set file directly on hidden input[type=file].
        fi = page.locator("input[type='file']").first
        if fi.count() == 0:
            raise RuntimeError(f"Upload failed and no file input found. chooser_error={upload_err}")
        fi.set_input_files(video_path, timeout=90000)
    next_btn = page.get_by_role("button", name="Next").last
    _wait_until(lambda: next_btn.count() > 0 and next_btn.is_enabled(), timeout_sec=60)
    page.screenshot(path=str(shot_dir / f"{plan.page_key}_03_uploaded.png"), full_page=True)

    # Optional description entry on create step.
    _fill_caption_on_page(page, caption)

    # Move Create -> Edit -> Share
    _retry_ui("click_next_1", lambda: page.get_by_role("button", name="Next").last.click(timeout=10000), shot_dir=shot_dir, page_key=plan.page_key)
    _wait_until(lambda: page.get_by_role("button", name="Next").count() > 0, timeout_sec=12)
    _retry_ui("click_next_2", lambda: page.get_by_role("button", name="Next").last.click(timeout=10000), shot_dir=shot_dir, page_key=plan.page_key)
    _wait_until(lambda: page.locator("div").filter(has_text=re.compile(r"Scheduling options", re.I)).count() > 0, timeout_sec=15)
    page.screenshot(path=str(shot_dir / f"{plan.page_key}_04_share.png"), full_page=True)

    # Re-apply caption on final share screen where Meta usually stores description.
    _fill_caption_on_page(page, caption)

    story_on = _set_story_toggle_on(page)
    _fill_schedule_time(page, when_dt, shot_dir, plan.page_key)
    page.screenshot(path=str(shot_dir / f"{plan.page_key}_05_schedule_set.png"), full_page=True)

    schedule_btn = page.get_by_role("button", name="Schedule").last
    deadline = time.time() + 45
    while time.time() < deadline:
        try:
            if schedule_btn.is_enabled():
                break
        except Exception:
            pass
        _wait_until(lambda: False, timeout_sec=0.5, poll_sec=0.5)
    if not schedule_btn.is_enabled():
        raise RuntimeError("Schedule button stayed disabled after fill.")
    _retry_ui("click_schedule", lambda: schedule_btn.click(timeout=10000), shot_dir=shot_dir, page_key=plan.page_key)
    _wait_until(
        lambda: (
            "reel scheduled" in page.locator("body").inner_text().lower()
            or "scheduled to publish" in page.locator("body").inner_text().lower()
        ),
        timeout_sec=20,
        poll_sec=0.8,
    )
    page.screenshot(path=str(shot_dir / f"{plan.page_key}_06_scheduled_result.png"), full_page=True)

    body = page.locator("body").inner_text().lower()
    ok = ("reel scheduled" in body) or ("scheduled to publish" in body)
    return {
        "ok": ok,
        "story_toggle_on": story_on,
        "target_time": when_dt.isoformat(),
        "url": page.url,
    }


def _upload_and_post_now(page, plan: PagePlan, video_path: str, caption: str, shot_dir: Path) -> dict:
    if "business.facebook.com" not in page.url and page.url:
        page.goto("about:blank")

    page.goto(
        f"https://business.facebook.com/latest/home?asset_id={plan.asset_id}",
        wait_until="domcontentloaded",
        timeout=120000,
    )
    _wait_until(lambda: page.get_by_role("button", name="Create Reel").count() > 0, timeout_sec=20)
    page.screenshot(path=str(shot_dir / f"{plan.page_key}_now_01_home.png"), full_page=True)

    _retry_ui("click_create_reel", lambda: page.get_by_role("button", name="Create Reel").click(timeout=20000), shot_dir=shot_dir, page_key=plan.page_key)
    _wait_until(lambda: page.get_by_role("button", name="Add video").count() > 0, timeout_sec=20)
    page.screenshot(path=str(shot_dir / f"{plan.page_key}_now_02_composer.png"), full_page=True)

    upload_ok = False
    upload_err = ""
    try:
        with page.expect_file_chooser(timeout=30000) as fc:
            _retry_ui("click_add_video", lambda: page.get_by_role("button", name="Add video").click(), shot_dir=shot_dir, page_key=plan.page_key)
        fc.value.set_files(video_path, timeout=90000)
        upload_ok = True
    except Exception as ex:
        upload_err = f"{type(ex).__name__}: {ex}"
    if not upload_ok:
        fi = page.locator("input[type='file']").first
        if fi.count() == 0:
            raise RuntimeError(f"Upload failed and no file input found. chooser_error={upload_err}")
        fi.set_input_files(video_path, timeout=90000)

    next_btn = page.get_by_role("button", name="Next").last
    if not _wait_until(lambda: next_btn.count() > 0 and next_btn.is_enabled(), timeout_sec=90):
        raise RuntimeError("Next button did not enable after upload.")
    page.screenshot(path=str(shot_dir / f"{plan.page_key}_now_03_uploaded.png"), full_page=True)

    _fill_caption_on_page(page, caption)

    _retry_ui("click_next_1", lambda: page.get_by_role("button", name="Next").last.click(timeout=10000), shot_dir=shot_dir, page_key=plan.page_key)
    _wait_until(lambda: page.get_by_role("button", name="Next").count() > 0, timeout_sec=15)
    _retry_ui("click_next_2", lambda: page.get_by_role("button", name="Next").last.click(timeout=10000), shot_dir=shot_dir, page_key=plan.page_key)
    _wait_until(lambda: page.get_by_role("button", name=re.compile(r"Share now|Share", re.I)).count() > 0, timeout_sec=20)
    page.screenshot(path=str(shot_dir / f"{plan.page_key}_now_04_share.png"), full_page=True)

    # Re-apply caption on final share screen where Meta usually stores description.
    _fill_caption_on_page(page, caption)

    # Ensure 'Share now' tab is selected.
    try:
        page.get_by_role("button", name=re.compile(r"^Share now$", re.I)).first.click(timeout=7000)
    except Exception:
        pass
    story_on = _set_story_toggle_on(page)

    # Footer primary CTA is often 'Share', not 'Share now'.
    primary_candidates = [
        page.get_by_role("button", name=re.compile(r"^Share$", re.I)).last,
        page.get_by_role("button", name=re.compile(r"^Share now$", re.I)).last,
    ]
    primary = None
    for cand in primary_candidates:
        try:
            if cand.count() > 0:
                primary = cand
                break
        except Exception:
            continue
    if primary is None:
        raise RuntimeError("Could not find primary Share button.")

    if not _wait_until(lambda: primary.is_enabled(), timeout_sec=25):
        raise RuntimeError("Share button stayed disabled.")
    _retry_ui("click_share", lambda: primary.click(timeout=10000), shot_dir=shot_dir, page_key=plan.page_key)
    page.screenshot(path=str(shot_dir / f"{plan.page_key}_now_05_after_click.png"), full_page=True)

    # Verification: broad success signals after click.
    ok = _wait_until(
        lambda: any(
            k in page.locator("body").inner_text().lower()
            for k in [
                "reel shared",
                "being shared",
                "published",
                "posted",
                "successfully shared",
                "your reel has been shared",
                "reel is being processed",
            ]
        ),
        timeout_sec=120,
        poll_sec=0.8,
    )
    page.screenshot(path=str(shot_dir / f"{plan.page_key}_now_06_result.png"), full_page=True)
    return {
        "ok": bool(ok),
        "story_toggle_on": story_on,
        "url": page.url,
    }


def _upload_and_schedule_with_retry(ctx, plan: PagePlan, video_path: str, caption: str, when_dt: datetime, shot_dir: Path) -> dict:
    """
    Try scheduling once; if it fails (exception or UI not-confirmed),
    retry one time on a fresh tab/context page.
    """
    attempts: list[dict] = []

    def _reset_meta_tabs() -> None:
        # Close stale Meta/Facebook tabs that can hijack focus/state between retries.
        # Keep this conservative: only close known business/composer surfaces.
        for p in list(ctx.pages):
            try:
                u = (p.url or "").lower()
                if ("business.facebook.com" in u) or ("facebook.com/latest/reels_composer" in u):
                    p.close()
            except Exception:
                continue

    for attempt in (1, 2):
        _reset_meta_tabs()
        page = ctx.new_page()
        page.bring_to_front()
        try:
            status = _upload_and_schedule(page, plan, video_path, caption, when_dt, shot_dir)
            status["attempt"] = attempt
            attempts.append(status)
            if bool(status.get("ok")):
                status["retried"] = attempt > 1
                status["attempts"] = attempts
                return status
        except Exception as ex:
            attempts.append(
                {
                    "ok": False,
                    "attempt": attempt,
                    "error": f"{type(ex).__name__}: {ex}",
                }
            )
        finally:
            if not page.is_closed():
                page.close()

    return {
        "ok": False,
        "retried": True,
        "attempts": attempts,
        "target_time": when_dt.isoformat(),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", default="", help="Optional page_key to run only one page plan.")
    args = ap.parse_args()

    plans = _load_plans()
    if args.page:
        plans = [p for p in plans if p.page_key == args.page]
        if not plans:
            raise RuntimeError(f"No enabled plan found for page: {args.page}")
    run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = RUN_LOG_DIR / run_stamp
    shot_dir = run_dir / "screens"
    run_dir.mkdir(parents=True, exist_ok=True)
    shot_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    results: list[dict] = []

    # 1) Generate all reels for day and freeze a queue file.
    queue_items: list[dict] = []
    for plan in plans:
        for slot in plan.slots:
            manifest, video, caption = _generate_reel(plan)
            when_dt = _schedule_dt_for_slot(slot, now)
            queue_items.append(
                {
                    "page_key": plan.page_key,
                    "asset_id": plan.asset_id,
                    "slot": slot,
                    "target_time": when_dt.isoformat(),
                    "manifest": str(manifest),
                    "video": video,
                    "caption": caption,
                }
            )

    queue_path = run_dir / "daily_batch_queue.json"
    queue_path.write_text(json.dumps({"created_at": datetime.now().isoformat(), "items": queue_items}, ensure_ascii=False, indent=2), encoding="utf-8")

    # 2) Schedule all via UI from frozen queue.
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:9100", timeout=120000)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        plan_map = {pl.page_key: pl for pl in plans}

        for item in queue_items:
            plan = plan_map[item["page_key"]]
            when_dt = datetime.fromisoformat(item["target_time"])
            status = _upload_and_schedule_with_retry(ctx, plan, item["video"], item["caption"], when_dt, shot_dir)
            results.append(
                {
                    "page_key": item["page_key"],
                    "slot": item["slot"],
                    "manifest": item["manifest"],
                    "video": item["video"],
                    "status": status,
                }
            )

    report = {"run_at": datetime.now().isoformat(), "queue_file": str(queue_path), "results": results}
    report_path = run_dir / "daily_batch_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"REPORT={report_path}")
    print(f"TOTAL={len(results)}")
    print(f"SUCCESS={sum(1 for r in results if r['status']['ok'])}")


if __name__ == "__main__":
    main()
