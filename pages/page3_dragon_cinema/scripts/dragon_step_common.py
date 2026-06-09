from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autovideo.services.grok_cli import is_grok_credit_error  # noqa: E402


def resolve_grok_paths(project_root: Path) -> tuple[Path, Path]:
    default_home = Path.home()
    if os.name != "nt":
        parts = project_root.resolve().parts
        if len(parts) >= 5 and parts[0] == "/" and parts[1] == "mnt" and parts[2].lower() == "c":
            windows_home = Path(*parts[:5])
            grok_exe = windows_home / ".grok" / "bin" / "grok.exe"
            if grok_exe.exists():
                return grok_exe, windows_home
    return default_home / ".grok" / "bin" / "grok.exe", default_home


def _wsl_to_windows_path(value: str) -> str:
    text = value.replace("\\", "/")
    if text.startswith("/mnt/") and len(text) > 6 and text[6] == "/":
        return f"{text[5].upper()}:/{text[7:]}"
    return value


def _prepare_windows_exe_cmd(cmd: list[str]) -> list[str]:
    if os.name == "nt" or not cmd or not str(cmd[0]).lower().endswith(".exe"):
        return cmd
    return [str(cmd[0]), *[_wsl_to_windows_path(str(part)) for part in cmd[1:]]]


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 600) -> str:
    cmd = _prepare_windows_exe_cmd(cmd)
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\nSTDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}")
    return p.stdout.strip()


def latest_mp4_newer_than(home: Path, since_ts: float) -> Path | None:
    base = home / ".grok" / "sessions"
    files = sorted(base.rglob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    for f in files:
        try:
            if f.stat().st_mtime > since_ts:
                return f
        except Exception:
            continue
    return None


def wait_for_stable_file(path: Path, checks: int = 2, sleep_sec: float = 1.5) -> None:
    last_size = -1
    stable_hits = 0
    while stable_hits < checks:
        size = path.stat().st_size if path.exists() else 0
        if size > 0 and size == last_size:
            stable_hits += 1
        else:
            stable_hits = 0
        last_size = size
        time.sleep(sleep_sec)


def is_grok_network_error(text: str) -> bool:
    lowered = str(text or "").lower()
    signals = [
        "dns error",
        "no such host",
        "error sending request",
        "request error",
        "failed to fetch models",
        "settings fetch network error",
        "reqwest error",
        "connecterror",
        "cli-chat-proxy.grok.com",
    ]
    return any(signal in lowered for signal in signals)


def run_grok_and_wait_for_mp4(
    grok_exe: Path,
    prompt: str,
    *,
    cwd: Path,
    home: Path,
    poll_sec: float = 3.0,
    max_wait_sec: int = 0,
) -> Path:
    max_attempts = 3
    retry_delays = [45, 90]
    last_error = ""
    for attempt in range(1, max_attempts + 1):
        start_ts = time.time()
        proc = subprocess.Popen(
            [str(grok_exe), "-p", prompt],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            while True:
                newest = latest_mp4_newer_than(home, start_ts - 0.5)
                if newest is not None:
                    wait_for_stable_file(newest)
                    try:
                        if proc.poll() is None:
                            proc.terminate()
                    except Exception:
                        pass
                    return newest

                if proc.poll() is not None:
                    out, err = proc.communicate(timeout=5)
                    combined = f"{out or ''}\n{err or ''}"
                    if is_grok_credit_error(combined):
                        raise RuntimeError(
                            "GROK_CREDITS_EXHAUSTED: Grok returned 403 spending/subscription limit. "
                            "Add credits or renew SuperGrok, then rerun the missed slots."
                        )
                    if is_grok_network_error(combined) and attempt < max_attempts:
                        last_error = combined
                        time.sleep(retry_delays[min(attempt - 1, len(retry_delays) - 1)])
                        break
                    raise RuntimeError(
                        "Grok exited before producing mp4.\n"
                        f"STDOUT:\n{out}\nSTDERR:\n{err}"
                    )

                if max_wait_sec > 0 and (time.time() - start_ts) > max_wait_sec:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    raise TimeoutError(
                        f"Grok mp4 did not appear within {max_wait_sec}s for prompt: {prompt[:120]}..."
                    )
                time.sleep(poll_sec)
        finally:
            try:
                if proc.poll() is None:
                    proc.terminate()
            except Exception:
                pass
    raise RuntimeError(
        "GROK_NETWORK_ERROR: Grok video generation failed after transient network retries.\n"
        f"Last error:\n{last_error}"
    )


def write_done_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
